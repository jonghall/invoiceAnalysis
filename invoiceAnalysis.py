#!/usr/bin/env python3
# invoiceAnalysis.py - Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.
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
#
# usage: invoiceAnalysis.py [-h] -k apikey -s YYYY-MM -e YYYY-MM [--COS_APIKEY COS_APIKEY] [--COS_ENDPOINT COS_ENDPOINT] [--COS_INSTANCE_CRN COS_INSTANCE_CRN] [--COS_BUCKET COS_BUCKET] [--output OUTPUT] [--SL_PRIVATE | --no-SL_PRIVATE]
# Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.
# optional arguments:
#   -h, --help            show this help message and exit
#   -k apikey, --IC_API_KEY apikey
#                         IBM Cloud API Key
#   -s YYYY-MM, --startdate YYYY-MM
#                        Start Year & Month in format YYYY-MM
#   -e YYYY-MM, --enddate YYYY-MM
#                         End Year & Month in format YYYY-MM
#   --COS_APIKEY COS_APIKEY
#                         COS apikey to use for Object Storage.
#   --COS_ENDPOINT COS_ENDPOINT
#                         COS endpoint to use for Object Storage.
#   --COS_INSTANCE_CRN COS_INSTANCE_CRN
#                         COS Instance CRN to use for file upload.
#   --COS_BUCKET COS_BUCKET
#                         COS Bucket name to use for file upload.
#   --output OUTPUT       Filename Excel output file. (including extension of .xlsx)
#   --SL_PRIVATE, --no-SL_PRIVATE
#                         Use IBM Cloud Classic Private API Endpoint (default: False)

__author__ = 'jonhall'

import SoftLayer, argparse, os, logging, logging.config, json
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pandas as pd
import numpy as np
from logdna import LogDNAHandler
import ibm_boto3
from ibm_botocore.client import Config, ClientError
from ibm_platform_services import IamIdentityV1, UsageReportsV4
from ibm_cloud_sdk_core import ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

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

def getInvoiceDates(startdate,enddate):
    # Adjust dates to match SLIC Invoice cutoffs
    month = int(startdate[5:7]) - 1
    year = int(startdate[0:4])
    if month == 0:
        year = year - 1
        month = 12
    day = 20
    startdate = datetime(year, month, day).strftime('%m/%d/%Y')

    month = int(enddate[5:7])
    year = int(enddate[0:4])
    day = 19
    enddate = datetime(year, month, day).strftime('%m/%d/%Y')
    return startdate, enddate

def getInvoiceList(startdate, enddate):
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

def getInvoiceDetail(startdate, enddate):
    #
    # GET InvoiceDetail
    #
    global IC_API_KEY, client, SL_ENDPOINT

    # Create Classic infra API client
    client = SoftLayer.Client(username="apikey", api_key=IC_API_KEY, endpoint_url=SL_ENDPOINT)

    # get list of invoices between start date and enddate
    invoiceList = getInvoiceList(startdate, enddate)

    # Create dataframe to work with for classic infrastructure invoices
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
    return df

def createReport(filename):
    # Write dataframe to excel
    global classicUsage, paasUsage, useMonth
    logging.info("Creating Pivots File.")
    writer = pd.ExcelWriter(filename, engine='xlsxwriter')
    workbook = writer.book

    #
    # Write detail tab
    #
    classicUsage.to_excel(writer, 'Detail')
    usdollar = workbook.add_format({'num_format': '$#,##0.00'})

    worksheet = writer.sheets['Detail']
    worksheet.set_column('P:S', 18, usdollar)

    #
    # Map Portal Invoices to SLIC Invoices
    #

    classicUsage["totalAmount"] = classicUsage["totalOneTimeAmount"] + classicUsage["totalRecurringCharge"]
    SLICInvoice = pd.pivot_table(classicUsage,
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
    invoiceSummary = pd.pivot_table(classicUsage, index=["Type", "Category"],
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

    categorySummary = pd.pivot_table(classicUsage, index=["Category", "Description"],
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
    virtualServers = classicUsage.query('Category == ["Computing Instance"] and Hourly == [True]')
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
    monthlyVirtualServers = classicUsage.query('Category == ["Computing Instance"] and Hourly == [False]')
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
    bareMetalServers = classicUsage.query('Category == ["Server"]and Hourly == [True]')
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
    monthlyBareMetalServers = classicUsage.query('Category == ["Server"] and Hourly == [False]')
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
    if len(paasUsage) >0:
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
                                        columns=[useMonth],
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
                                     columns=[useMonth],
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

def getAccountId(IC_API_KEY):
    ##########################################################
    ## Get Account from the passed API Key
    ##########################################################

    logging.info("Retrieving IBM Cloud Account ID from ApiKey.")
    try:
        authenticator = IAMAuthenticator(IC_API_KEY)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit()
    try:
        iam_identity_service = IamIdentityV1(authenticator=authenticator)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit()

    try:
        api_key = iam_identity_service.get_api_keys_details(
          iam_api_key=IC_API_KEY
        ).get_result()
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit()

    return api_key["account_id"]

def accountUsage(startdate, enddate):
    ##########################################################
    ## Get Usage for Account matching recuring invoice periods
    ##########################################################
    global IC_ACCOUNT_ID, IC_API_KEY


    try:
        authenticator = IAMAuthenticator(IC_API_KEY)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit()
    try:
        usage_reports_service = UsageReportsV4(authenticator=authenticator)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        quit()

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
        try:
            usage = usage_reports_service.get_account_usage(
                account_id=IC_ACCOUNT_ID,
                billingmonth=usageMonth,
                names=True
            ).get_result()
        except ApiException as e:
            logging.error("API exception {}.".format(str(e)))
            quit()
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
        description="Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.")
    parser.add_argument("-k", "--IC_API_KEY", default=os.environ.get('IC_API_KEY', None), required=True, metavar="apikey", help="IBM Cloud API Key")
    parser.add_argument("-s", "--startdate", default=os.environ.get('startdate', None), required=True, metavar="YYYY-MM", help="Start Year & Month in format YYYY-MM")
    parser.add_argument("-e", "--enddate", default=os.environ.get('enddate', None),required=True, metavar="YYYY-MM", help="End Year & Month in format YYYY-MM")
    parser.add_argument("--COS_APIKEY", default=os.environ.get('COS_APIKEY', None), help="COS apikey to use for Object Storage.")
    parser.add_argument("--COS_ENDPOINT", default=os.environ.get('COS_ENDPOINT', None), help="COS endpoint to use for Object Storage.")
    parser.add_argument("--COS_INSTANCE_CRN", default=os.environ.get('COS_INSTANCE_CRN', None), help="COS Instance CRN to use for file upload.")
    parser.add_argument("--COS_BUCKET", default=os.environ.get('COS_BUCKET', None), help="COS Bucket name to use for file upload.")
    parser.add_argument("--output", default=os.environ.get('output', 'invoice-analysis.xlsx'), help="Filename Excel output file. (including extension of .xlsx)")
    parser.add_argument("--SL_PRIVATE", default=False, action=argparse.BooleanOptionalAction, help="Use IBM Cloud Classic Private API Endpoint")
    parser.add_argument("--PAAS_USE_USAGE_MONTH", default=False, action=argparse.BooleanOptionalAction, help="Use actual PaaS usage month for pivots instead of IBM Invoice Month which matches IBM invoices.")
    args = parser.parse_args()

    IC_API_KEY = args.IC_API_KEY

    # Calculate invoice dates based on SLIC invoice cutoffs.
    startdate, enddate = getInvoiceDates(args.startdate, args.enddate)

    # Change endpoint to private Endpoint if command line open chosen
    if args.SL_PRIVATE:
        SL_ENDPOINT = "https://api.service.softlayer.com/xmlrpc/v3.1"
    else:
        SL_ENDPOINT = "https://api.softlayer.com/xmlrpc/v3.1"

    #  Retrieve Invoices from classic
    classicUsage = getInvoiceDetail(startdate, enddate)

    # Retrieve Usage from IBM Cloud
    IC_ACCOUNT_ID = getAccountId(IC_API_KEY)
    if args.PAAS_USE_USAGE_MONTH:
        useMonth = "usageMonth"
    else:
        useMonth = "invoiceMonth"

    paasUsage = accountUsage(startdate, enddate)

    # Build Exel Report
    createReport(args.output)

    # upload created file to COS if COS credentials provided
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
