#!/usr/bin/env python3
# invoiceAnalysis.py - A script to export IBM Cloud Classic Infrastructure Invoices
# Author: Jon Hall
# Copyright (c) 2021
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
#   Get RECURRING, NEW, and Onetime Invoices with a invoice amount > 0
#   Return toplevel items and export to excel spreadsheet
__author__ = 'jonhall'

import SoftLayer, argparse, os, logging, logging.config, json, requests, urllib
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
from logdna import LogDNAHandler
import ibm_boto3
from ibm_botocore.client import Config, ClientError

def setup_logging(default_path='logging.json', default_level=logging.info, env_key='LOG_CFG'):

    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = json.load(f)
        if "handlers" in config:
            if "logdna" in config["handlers"]:
                config["handlers"]["logdna"]["key"] = os.getenv("logdna_ingest_key")
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

def getDescription(categoryCode, detail):
    for item in detail:
        if 'categoryCode' in item:
            if item['categoryCode'] == categoryCode:
                return item['product']['description'].strip()
    return ""

def getSLIClinvoicedate(invoiceDate):
    # Determine SLIC  Invoice (20th prev month - 19th of month) from portal invoice make current month SLIC invoice.
    year = invoiceDate.year
    month = invoiceDate.month
    day = invoiceDate.day
    if day <= 19:
        month = month + 0
    else:
        month = month + 1

    if month > 12:
        month = month - 12
        year = year + 1
    return datetime(year, month, 1).strftime('%Y-%m')

def getInvoices(startdate, enddate):
    #
    # GET LIST OF INVOICES BETWEEN DATES
    #
    logging.info("Looking up invoices from {} to {}....".format(startdate, enddate))

    # Build Filter for Invoices
    try:
        invoiceList = client['Account'].getInvoices(mask='id,createDate,typeCode,invoiceTotalAmount,invoiceTotalRecurringAmount,invoiceTopLevelItemCount', filter={
                'invoices': {
                    'createDate': {
                        'operation': 'betweenDate',
                        'options': [
                             {'name': 'startDate', 'value': [startdate+" 0:0:0"]},
                             {'name': 'endDate', 'value': [enddate+" 23:59:59"]}
                        ]
                    }
                }
        })
    except SoftLayer.SoftLayerAPIError as e:
        logging.error("Account::getInvoices: %s, %s" % (e.faultCode, e.faultString))
        quit()
    return invoiceList

def getInvoiceDetail(invoiceList):
    #
    # GET InvoiceDetail
    #
    global df, invoicePivot
    for invoice in invoiceList:
        if float(invoice['invoiceTotalAmount']) == 0:
            #Skip because zero balance
            continue

        invoiceID = invoice['id']
        invoiceDate = datetime.strptime(invoice['createDate'][:10], "%Y-%m-%d")
        invoiceTotalAmount = float(invoice['invoiceTotalAmount'])

        SLICInvoiceDate = getSLIClinvoicedate(invoiceDate)

        invoiceTotalRecurringAmount = float(invoice['invoiceTotalRecurringAmount'])
        invoiceType = invoice['typeCode']
        totalItems = invoice['invoiceTopLevelItemCount']

        # PRINT INVOICE SUMMARY LINE
        logging.info('Invoice: {} Date: {} Type:{} Items: {} Amount: ${:,.2f}'.format(invoiceID, datetime.strftime(invoiceDate, "%Y-%m-%d"),invoiceType, totalItems, invoiceTotalRecurringAmount))

        limit = 250 ## set limit of record returned
        for offset in range(0, totalItems, limit):
            if ( totalItems - offset - limit ) < 0:
                remaining = totalItems - offset
            logging.info("Retrieving %s invoice line items for Invoice %s at Offset %s of %s" % (limit, invoiceID, offset, totalItems))

            try:
                Billing_Invoice = client['Billing_Invoice'].getInvoiceTopLevelItems(id=invoiceID, limit=limit, offset=offset,
                                    mask='id, billingItemId, categoryCode, category.name, hourlyFlag, hostName, domainName, product.description, createDate, totalRecurringAmount, totalOneTimeAmount, usageChargeFlag, hourlyRecurringFee, children.description, children.categoryCode, children.product, children.hourlyRecurringFee')
            except SoftLayer.SoftLayerAPIError as e:
                logging.error("Billing_Invoice::getInvoiceTopLevelItems: %s, %s" % (e.faultCode, e.faultString))
                quit()

            count = 0
            # ITERATE THROUGH DETAIL
            for item in Billing_Invoice:
                totalOneTimeAmount = float(item['totalOneTimeAmount'])
                billingItemId = item['billingItemId']
                category = item["categoryCode"]
                categoryName = item["category"]["name"]
                description = item['product']['description']
                memory = getDescription("ram", item["children"])
                os = getDescription("os", item["children"])

                if 'hostName' in item:
                    if 'domainName' in item:
                        hostName = item['hostName']+"."+item['domainName']
                    else:
                        hostName = item['hostName']
                else:
                    hostName = ""

                recurringFee = float(item['totalRecurringAmount'])

                # If Hourly calculate hourly rate and total hours
                if item["hourlyFlag"]:
                    if float(item["hourlyRecurringFee"]) > 0:

                        hourlyRecurringFee = float(item['hourlyRecurringFee']) + sum(
                            float(child['hourlyRecurringFee']) for child in item["children"])
                        hours = round(float(recurringFee) / hourlyRecurringFee)
                    else:
                        hourlyRecurringFee = 0
                        hours = 0
                # Not an hourly billing item
                else:
                    hourlyRecurringFee = 0
                    hours = 0

                # Special handling for storage
                if category == "storage_service_enterprise" or category == "performance_storage_iscsi":

                    if category == "storage_service_enterprise":
                        iops = getDescription("storage_tier_level", item["children"])
                        storage = getDescription("performance_storage_space", item["children"])
                        snapshot = getDescription("storage_snapshot_space", item["children"])
                        if snapshot == "":
                            description = storage + " " + iops + " "
                        else:
                            description = storage+" " + iops + " with " + snapshot
                    else:
                        iops = getDescription("performance_storage_iops", item["children"])
                        storage = getDescription("performance_storage_space", item["children"])
                        description = storage + " " + iops
                else:
                    description = description.replace('\n', " ")

                # Append record to dataframe
                row = {'Portal_Invoice_Date': invoiceDate.strftime("%Y-%m-%d"),
                       'IBM_Invoice_Month': SLICInvoiceDate,
                       'Portal_Invoice_Number': invoiceID,
                       'BillingItemId': billingItemId,
                       'hostName': hostName,
                       'Category': categoryName,
                       'Description': description,
                       'Memory': memory,
                       'OS': os,
                       'Hourly': item["hourlyFlag"],
                       'Usage': item["usageChargeFlag"],
                       'Hours': hours,
                       'HourlyRate': round(hourlyRecurringFee,3),
                       'totalRecurringCharge': round(recurringFee,3),
                       'totalOneTimeAmount': float(totalOneTimeAmount),
                       'InvoiceTotal': float(invoiceTotalAmount),
                       'InvoiceRecurring': float(invoiceTotalRecurringAmount),
                       'Type': invoiceType
                        }


                df = df.append(row, ignore_index=True)

def createReport(filename, paas):
    # Write dataframe to excel
    global df, paasUsage
    logging.info("Creating Pivots File.")
    writer = pd.ExcelWriter(filename, engine='xlsxwriter')
    workbook = writer.book

    #
    # Write detail tab
    #
    df.to_excel(writer, 'Detail')
    usdollar = workbook.add_format({'num_format': '$#,##0.00'})

    worksheet = writer.sheets['Detail']
    worksheet.set_column('P:S', 18, usdollar)

    #
    # Map Portal Invoices to SLIC Invoices
    #

    df["totalAmount"] = df["totalOneTimeAmount"] + df["totalRecurringCharge"]
    SLICInvoice = pd.pivot_table(df,
                                 index=["IBM_Invoice_Month", "Portal_Invoice_Date", "Portal_Invoice_Number", "Type"],
                                 values=["totalAmount"],
                                 aggfunc={'totalAmount': np.sum}, fill_value=0)
    out = pd.concat([d.append(d.sum().rename((k, '-', '-', 'Total'))) for k, d in SLICInvoice.groupby('IBM_Invoice_Month')])

    out.to_excel(writer, 'InvoiceMap')
    worksheet = writer.sheets['InvoiceMap']
    format1 = workbook.add_format({'num_format': '$#,##0.00'})
    format2 = workbook.add_format({'align': 'left'})
    worksheet.set_column("A:D", 20, format2)
    worksheet.set_column("E:ZZ", 18, format1)

    #
    # Build a pivot table by Invoice Type
    #
    invoiceSummary = pd.pivot_table(df, index=["Type", "Category"],
                            values=["totalAmount"],
                            columns=['IBM_Invoice_Month'],
                            aggfunc={'totalAmount': np.sum,}, margins=True, margins_name="Total", fill_value=0).\
                                    rename(columns={'totalRecurringCharge': 'TotalRecurring'})
    invoiceSummary.to_excel(writer, 'InvoiceSummary')
    worksheet = writer.sheets['InvoiceSummary']
    format1 = workbook.add_format({'num_format': '$#,##0.00'})
    format2 = workbook.add_format({'align': 'left'})
    worksheet.set_column("A:A", 20, format2)
    worksheet.set_column("B:B", 40, format2)
    worksheet.set_column("C:ZZ", 18, format1)


    #
    # Build a pivot table by Category with totalRecurringCharges

    categorySummary = pd.pivot_table(df, index=["Category", "Description"],
                            values=["totalAmount"],
                            columns=['IBM_Invoice_Month'],
                            aggfunc={'totalAmount': np.sum}, margins=True, margins_name="Total", fill_value=0)
    categorySummary.to_excel(writer, 'CategorySummary')
    worksheet = writer.sheets['CategorySummary']
    format1 = workbook.add_format({'num_format': '$#,##0.00'})
    format2 = workbook.add_format({'align': 'left'})
    worksheet.set_column("A:A", 40, format2)
    worksheet.set_column("B:B", 40, format2)
    worksheet.set_column("C:ZZ", 18, format1)

    #
    # Build a pivot table for Hourly VSI's with totalRecurringCharges
    #
    virtualServers = df.query('Category == ["Computing Instance"] and Hourly == [True]')
    if len(virtualServers) > 0:
        virtualServerPivot = pd.pivot_table(virtualServers, index=["Description", "OS"],
                                values=["Hours", "totalRecurringCharge"],
                                columns=['IBM_Invoice_Month'],
                                aggfunc={'Description': len, 'Hours': np.sum, 'totalRecurringCharge': np.sum}, fill_value=0).\
                                        rename(columns={"Description": 'qty', 'Hours': 'Total Hours', 'totalRecurringCharge': 'TotalRecurring'})
        virtualServerPivot.to_excel(writer, 'HrlyVirtualServerPivot')
        worksheet = writer.sheets['HrlyVirtualServerPivot']

    #
    # Build a pivot table for Monthly VSI's with totalRecurringCharges
    #
    monthlyVirtualServers = df.query('Category == ["Computing Instance"] and Hourly == [False]')
    if len(monthlyVirtualServers) > 0:
        virtualServerPivot = pd.pivot_table(monthlyVirtualServers, index=["Description", "OS"],
                                values=["totalRecurringCharge"],
                                columns=['IBM_Invoice_Month'],
                                aggfunc={'Description': len, 'totalRecurringCharge': np.sum}, fill_value=0).\
                                        rename(columns={"Description": 'qty', 'totalRecurringCharge': 'TotalRecurring'})
        virtualServerPivot.to_excel(writer, 'MnthlyVirtualServerPivot')
        worksheet = writer.sheets['MnthlyVirtualServerPivot']


    #
    # Build a pivot table for Hourly Bare Metal with totalRecurringCharges
    #
    bareMetalServers = df.query('Category == ["Server"]and Hourly == [True]')
    if len(bareMetalServers) > 0:
        bareMetalServerPivot = pd.pivot_table(bareMetalServers, index=["Description", "OS"],
                                values=["Hours", "totalRecurringCharge"],
                                columns=['IBM_Invoice_Month'],
                                aggfunc={'Description': len,  'totalRecurringCharge': np.sum}, fill_value=0).\
                                        rename(columns={"Description": 'qty', 'Hours': np.sum, 'totalRecurringCharge': 'TotalRecurring'})
        bareMetalServerPivot.to_excel(writer, 'HrlyBaremetalServerPivot')
        worksheet = writer.sheets['HrlyBaremetalServerPivot']

    #
    # Build a pivot table for Monthly Bare Metal with totalRecurringCharges
    #
    monthlyBareMetalServers = df.query('Category == ["Server"] and Hourly == [False]')
    if len(monthlyBareMetalServers) > 0:
        monthlyBareMetalServerPivot = pd.pivot_table(monthlyBareMetalServers, index=["Description", "OS"],
                                values=["totalRecurringCharge"],
                                columns=['IBM_Invoice_Month'],
                                aggfunc={'Description': len,  'totalRecurringCharge': np.sum}, fill_value=0).\
                                        rename(columns={"Description": 'qty', 'totalRecurringCharge': 'TotalRecurring'})
        monthlyBareMetalServerPivot.to_excel(writer, 'MthlyBaremetalServerPivot')
        worksheet = writer.sheets['MthlyBaremetalServerPivot']
        format1 = workbook.add_format({'num_format': '$#,##0.00'})
        format2 = workbook.add_format({'align': 'left'})
        worksheet.set_column("A:A", 40, format2)
        worksheet.set_column("B:B", 40, format2)

    # IF PaaS credential included add usage reports
    if paas:
        paasUsage.to_excel(writer, 'PaaS_Usage')
        worksheet = writer.sheets['PaaS_Usage']
        format1 = workbook.add_format({'num_format': '$#,##0.00'})
        format2 = workbook.add_format({'align': 'left'})
        worksheet.set_column("A:C", 12, format2)
        worksheet.set_column("D:E", 25, format2)
        worksheet.set_column("F:G", 18, format1)
        worksheet.set_column("H:I", 25, format2)
        worksheet.set_column("J:J", 18, format1)

        paasSummary = pd.pivot_table(paasUsage, index=["resource_name"],
                                        values=["charges"],
                                        columns=['usageMonth'],
                                        aggfunc={'charges': np.sum, }, margins=True, margins_name="Total",
                                        fill_value=0)
        paasSummary.to_excel(writer, 'PaaS_Summary')
        worksheet = writer.sheets['PaaS_Summary']
        format1 = workbook.add_format({'num_format': '$#,##0.00'})
        format2 = workbook.add_format({'align': 'left'})
        worksheet.set_column("A:A", 35, format2)
        worksheet.set_column("B:ZZ", 18, format1)

        paasSummaryPlan = pd.pivot_table(paasUsage, index=["resource_name", "plan_name"],
                                     values=["charges"],
                                     columns=['usageMonth'],
                                     aggfunc={'charges': np.sum, }, margins=True, margins_name="Total",
                                     fill_value=0)
        paasSummaryPlan.to_excel(writer, 'PaaS_Plan_Summary')
        worksheet = writer.sheets['PaaS_Plan_Summary']
        format1 = workbook.add_format({'num_format': '$#,##0.00'})
        format2 = workbook.add_format({'align': 'left'})
        worksheet.set_column("A:B", 35, format2)
        worksheet.set_column("C:ZZ", 18, format1)

    writer.save()

def multi_part_upload(bucket_name, item_name, file_path):
    try:
        logging.info("Starting file transfer for {0} to bucket: {1}".format(item_name, bucket_name))
        # set 5 MB chunks
        part_size = 1024 * 1024 * 5

        # set threadhold to 15 MB
        file_threshold = 1024 * 1024 * 15

        # set the transfer threshold and chunk size
        transfer_config = ibm_boto3.s3.transfer.TransferConfig(
            multipart_threshold=file_threshold,
            multipart_chunksize=part_size
        )

        # the upload_fileobj method will automatically execute a multi-part upload
        # in 5 MB chunks for all files over 15 MB
        with open(file_path, "rb") as file_data:
            cos.Object(bucket_name, item_name).upload_fileobj(
                Fileobj=file_data,
                Config=transfer_config
            )
        logging.info("Transfer for {0} complete".format(item_name))
    except ClientError as be:
        logging.error("CLIENT ERROR: {0}".format(be))
    except Exception as e:
        logging.error("Unable to complete multi-part upload: {0}".format(e))

def getiamtoken(apiKey,iam_endpoint):
    ################################################
    ## Get Bearer Token using apiKey
    ################################################

    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}

    parms = {"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": apiKey}

    try:
        resp = requests.post(iam_endpoint + "/identity/token?" + urllib.parse.urlencode(parms),
                             headers=headers, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as errc:
        logging.error("Error Connecting: {}".format(errc))
        quit()
    except requests.exceptions.Timeout as errt:
        logging.error("Timeout Error: {}".format(errt))
        quit()
    except requests.exceptions.HTTPError as errb:
        logging.error("Invalid token request {} {}.".format(errb, resp.text))
        quit()

    iam = resp.json()

    iamtoken = {"Authorization": "Bearer " + iam["access_token"]}

    return iamtoken

def getusage(accountId, iamToken, BILLING_ENDPOINT, month):
    # Get a list of current resource groups in accountId

    try:
        resp = requests.get(BILLING_ENDPOINT + '/v4/accounts/' + accountId + '/usage/' + month + "?_names=True",  headers=iamToken, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as errc:
        logging.error("Error Connecting to billing endpoint: {}.".format(errc))
        quit()
    except requests.exceptions.Timeout as errt:
        logging.error("Timeout Error: {}".format(errt))
        quit()
    except requests.exceptions.HTTPError as errb:
        if resp.status_code == 400:
            logging.error("Invalid get billing usage request {}.".format(errb))
            quit()
        elif resp.status_code == 401:
            logging.error("Your access token is invalid or authentication of your token failed.")
            quit()
        elif resp.status_code == 403:
            logging.error("Your access token is valid but does not have the necessary permissions to access this resource.")
            quit()

    if resp.status_code == 200:
        accountUsage = json.loads(resp.content)
    else:
        logging.error("Unexpected Error getting account usage, error code = {}.".format(resp.status_code))
        quit()
    return accountUsage

def accountUsage(IC_ACCOUNT, IC_API_KEY, IAM_ENDPOINT, BILLING_ENDPOINT, startdate, enddate):
    ##########################################################
    ## Get Usage for Account matching recuring invoice periods
    ##########################################################

    # Get IBM Cloud IAM token
    iamToken = getiamtoken(IC_API_KEY, IAM_ENDPOINT)

    accountUsage = pd.DataFrame(columns=['usageMonth',
                               'invoiceMonth',
                               'resource_name',
                               'plan_name',
                               'billable_charges',
                               'non_billable_charges',
                               'unit',
                               'quantity',
                               'charges']
                                )

    # PaaS consumption is delayed by one recurring invoice (ie April usage on June 1 recurring invoice)
    paasStart = datetime.strptime(startdate, '%m/%d/%Y') - relativedelta(months=1)
    paasEnd = datetime.strptime(enddate, '%m/%d/%Y') - relativedelta(months=2)

    while paasStart <= paasEnd + relativedelta(days=1):
        usageMonth = paasStart.strftime('%Y-%m')
        recurringMonth = paasStart + relativedelta(months=2)
        recurringMonth = recurringMonth.strftime('%Y-%m')
        logging.info("Retrieving PaaS Usage from {}.".format(usageMonth))

        usage = getusage(IC_ACCOUNT,iamToken, BILLING_ENDPOINT, usageMonth)
        paasStart += relativedelta(months=1)
        for u in usage['resources']:
            for p in u['plans']:
                for x in p['usage']:
                    row = {
                        'usageMonth': usageMonth,
                        'invoiceMonth': recurringMonth,
                        'resource_name': u['resource_name'],
                        'billable_charges': u["billable_cost"],
                        'non_billable_charges': u["non_billable_cost"],
                        'plan_name': p["plan_name"],
                        'unit': x["unit"],
                        'quantity': x["quantity"],
                        'charges': x["cost"],
                    }
                    accountUsage = accountUsage.append(row, ignore_index=True)
    return accountUsage


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Export detail to Excel file from all IBM Cloud Classic invoices types between two months.")
    parser.add_argument("-s", "--startdate", default=os.environ.get('startdate', None),help="Start Year & Month in format YYYY/MM")
    parser.add_argument("-e", "--enddate", default=os.environ.get('enddate', None),help="End Year & Month in format YYYY/MM")
    parser.add_argument("--SL_USER", default=os.environ.get('SL_USER', None), help="IBM Cloud Classic API Key Username")
    parser.add_argument("--SL_API_KEY", default=os.environ.get('SL_API_KEY', None), help="IBM Cloud Classic API Key")
    parser.add_argument("--SL_PRIVATE", default=False, action=argparse.BooleanOptionalAction, help="Use IBM Cloud Classic Private API Endpoint")
    parser.add_argument("--output", default=os.environ.get('output', 'invoice-analysis.xlsx'), help="Filename Excel output file. (including extension of .xlsx)")
    parser.add_argument("--COS_ENDPOINT", default=os.environ.get('COS_ENDPOINT', None), help="COS endpoint to use for Object Storage.")
    parser.add_argument("--COS_APIKEY", default=os.environ.get('COS_APIKEY', None), help="COS apikey to use for Object Storage.")
    parser.add_argument("--COS_INSTANCE_CRN", default=os.environ.get('COS_INSTANCE_CRN', None), help="COS Instance CRN to use for file upload.")
    parser.add_argument("--COS_BUCKET", default=os.environ.get('COS_BUCKET', None), help="COS Bucket name to use for file upload.")
    parser.add_argument("--IC_ACCOUNT", default=os.environ.get('IC_ACCOUNT', None), help="IBM Cloud Account ID")
    parser.add_argument("--IC_API_KEY", default=os.environ.get('IC_API_KEY', None), help="IBM Cloud API Key")
    parser.add_argument("--BILLING_ENDPOINT", default=os.environ.get("BILLING_ENDPOINT", "https://billing.cloud.ibm.com"), help="IBM Cloud Billing API endpoint.")
    parser.add_argument("--IAM_ENDPOINT", default=os.environ.get("IAM_ENDPOINT", "https://iam.cloud.ibm.com"), help="IBM Cloud IAM endpoint.")
    args = parser.parse_args()

    if args.SL_PRIVATE:
        SL_ENDPOINT = "https://api.service.softlayer.com/xmlrpc/v3.1"
    else:
        SL_ENDPOINT = "https://api.softlayer.com/xmlrpc/v3.1"

    if args.SL_USER == None or args.SL_API_KEY == None:
        logging.warning("IBM Cloud Classic Username & apiKey not specified and not set via environment variables, using default API keys.")
        client = SoftLayer.Client()
    else:
        client = SoftLayer.Client(username=args.SL_USER, api_key=args.SL_API_KEY, endpoint_url=SL_ENDPOINT)

    if args.startdate == None:
        logging.error("You must provide a start month and year date in the format of YYYY/MM.")
        quit()
    else:
        month = int(args.startdate[5:7]) - 1
        year = int(args.startdate[0:4])
        if month == 0:
            year = year - 1
            month = 12
        day = 20
        startdate = datetime(year, month, day).strftime('%m/%d/%Y')

    if args.enddate == None:
        logging.error("You must provide an end date in the format of MM/DD/YYYY.")
        quit()
    else:
        month = int(args.enddate[5:7])
        year = int(args.enddate[0:4])
        day = 19
        enddate = datetime(year, month, day).strftime('%m/%d/%Y')

    # Create dataframe to work with

    df = pd.DataFrame(columns=['Portal_Invoice_Date',
                               'IBM_Invoice_Month',
                               'Portal_Invoice_Number',
                               'Type',
                               'BillingItemId',
                               'hostName',
                               'Category',
                               'Description',
                               'Memory',
                               'OS',
                               'Hourly',
                               'Usage',
                               'Hours',
                               'HourlyRate',
                               'totalRecurringCharge',
                               'totalOneTimeAmount',
                               'InvoiceTotal',
                               'InvoiceRecurring'])

    invoiceList = getInvoices(startdate, enddate)
    getInvoiceDetail(invoiceList)
    paas = False
    if args.IC_ACCOUNT != None:
        paasUsage = accountUsage(args.IC_ACCOUNT, args.IC_API_KEY, args.IAM_ENDPOINT, args.BILLING_ENDPOINT, startdate, enddate)
        paas = True
    createReport(args.output, paas)

    # upload created file to COS
    if args.COS_APIKEY != None:
        cos = ibm_boto3.resource("s3",
                                 ibm_api_key_id=args.COS_APIKEY,
                                 ibm_service_instance_id=args.COS_INSTANCE_CRN,
                                 config=Config(signature_version="oauth"),
                                 endpoint_url=args.COS_ENDPOINT
                                 )
        multi_part_upload(args.COS_BUCKET, args.output, "./" + args.output)

        #cleanup file
        logging.info("Deleting {} local file.".format(args.output))
        os.remove("./"+args.output)
