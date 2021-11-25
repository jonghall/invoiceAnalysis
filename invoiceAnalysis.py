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
import SoftLayer, os, logging, logging.config, json, calendar, uuid, os.path, argparse, pytz
import pandas as pd
import numpy as np
from datetime import datetime, tzinfo, timezone
from dateutil import tz
from calendar import monthrange
from dateutil.relativedelta import relativedelta
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
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

def getDescription(categoryCode, detail):
    for item in detail:
        if 'categoryCode' in item:
            if item['categoryCode'] == categoryCode:
                return item['product']['description'].strip()
    return ""

def getStorageServiceUsage(categoryCode, detail):
    for item in detail:
        if 'categoryCode' in item:
            if item['categoryCode'] == categoryCode:
                return item['description'].strip()
    return ""


def getCFTSlinvoicedate(invoiceDate):
    # Determine CFTS Invoice Month (20th of prev month - 19th of current month) are on current month CFTS invoice.
    if invoiceDate.day > 19:
        invoiceDate = invoiceDate + relativedelta(months=1)
    return invoiceDate.strftime('%Y-%m')

def getInvoiceDates(startdate,enddate):
    # Adjust start and dates to match CFTS Invoice cutoffs of 20th to end of day 19th 00:00 UTC time on the 20th
    startdate = datetime(int(startdate[0:4]),int(startdate[5:7]),20,0,0,0,tzinfo=timezone.utc) - relativedelta(months=1)
    enddate = datetime(int(enddate[0:4]),int(enddate[5:7]),20,0,0,0,tzinfo=timezone.utc)
    return startdate, enddate

def getInvoiceList(startdate, enddate):
    # GET LIST OF PORTAL INVOICES BETWEEN DATES USING CENTRAL (DALLAS) TIME
    dallas=tz.gettz('US/Central')
    logging.info("Looking up invoices from {} to {}.".format(startdate.strftime("%m/%d/%Y %H:%M:%S%z"), enddate.strftime("%m/%d/%Y %H:%M:%S%z")))
    # filter invoices based on local dallas time that correspond to CFTS UTC cutoff
    try:
        invoiceList = client['Account'].getInvoices(mask='id,createDate,typeCode,invoiceTotalAmount,invoiceTotalRecurringAmount,invoiceTopLevelItemCount', filter={
                'invoices': {
                    'createDate': {
                        'operation': 'betweenDate',
                        'options': [
                             {'name': 'startDate', 'value': [startdate.astimezone(dallas).strftime("%m/%d/%Y %H:%M:%S")]},
                             {'name': 'endDate', 'value': [enddate.astimezone(dallas).strftime("%m/%d/%Y %H:%M:%S")]}
                        ]
                    }
                }
        })
    except SoftLayer.SoftLayerAPIError as e:
        logging.error("Account::getInvoices: %s, %s" % (e.faultCode, e.faultString))
        quit()
    return invoiceList

def getInvoiceDetail(IC_API_KEY, SL_ENDPOINT, startdate, enddate):
    #
    # GET InvoiceDetail
    #
    global client
    # Create dataframe to work with for classic infrastructure invoices
    df = pd.DataFrame(columns=['Portal_Invoice_Date',
                               'Portal_Invoice_Time',
                               'Service_Date_Start',
                               'Service_Date_End',
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
                               'NewEstimatedMonthly',
                               'totalOneTimeAmount',
                               'InvoiceTotal',
                               'InvoiceRecurring',
                               'Recurring_Description'])


    # Create Classic infra API client
    client = SoftLayer.Client(username="apikey", api_key=IC_API_KEY, endpoint_url=SL_ENDPOINT)

    # get list of invoices between start date and enddate
    invoiceList = getInvoiceList(startdate, enddate)

    if invoiceList == None:
        return invoiceList

    for invoice in invoiceList:
        if float(invoice['invoiceTotalAmount']) == 0:
            continue

        invoiceID = invoice['id']
        # To align to CFTS billing convert to UTC time.
        invoiceDate = datetime.strptime(invoice['createDate'], "%Y-%m-%dT%H:%M:%S%z").astimezone(pytz.utc)
        invoiceTotalAmount = float(invoice['invoiceTotalAmount'])
        CFTSInvoiceDate = getCFTSlinvoicedate(invoiceDate)

        invoiceTotalRecurringAmount = float(invoice['invoiceTotalRecurringAmount'])
        invoiceType = invoice['typeCode']
        recurringDesc = ""
        if invoiceType == "NEW":
            serviceDateStart = invoiceDate
            # get last day of month
            serviceDateEnd= serviceDateStart.replace(day=calendar.monthrange(serviceDateStart.year,serviceDateStart.month)[1])

        if invoiceType == "CREDIT" or invoiceType == "ONE-TIME-CHARGE":
            serviceDateStart = invoiceDate
            serviceDateEnd = invoiceDate

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
                NewEstimatedMonthly = 0

                # If Hourly calculate hourly rate and total hours
                if item["hourlyFlag"]:
                    # if hourly charges are previous month usage
                    serviceDateStart = invoiceDate - relativedelta(months=1)
                    serviceDateEnd = serviceDateStart.replace(day=calendar.monthrange(serviceDateStart.year, serviceDateStart.month)[1])
                    recurringDesc = "IaaS Usage"
                    hourlyRecurringFee = 0
                    hours = 0
                    if "hourlyRecurringFee" in item:
                        if float(item["hourlyRecurringFee"]) > 0:
                            hourlyRecurringFee = float(item['hourlyRecurringFee'])
                            for child in item["children"]:
                                if "hourlyRecurringFee" in child:
                                    hourlyRecurringFee = hourlyRecurringFee + float(child['hourlyRecurringFee'])
                            hours = round(float(recurringFee) / hourlyRecurringFee)            # Not an hourly billing item
                else:
                    if categoryName.find("Platform Service Plan") != -1:
                        # Non Hourly PaaS Usage from actual usage two months prior
                        serviceDateStart = invoiceDate - relativedelta(months=2)
                        serviceDateEnd = serviceDateStart.replace(day=calendar.monthrange(serviceDateStart.year, serviceDateStart.month)[1])
                        recurringDesc = "Platform Service Usage"
                    else:
                        if invoiceType == "RECURRING":
                            serviceDateStart = invoiceDate
                            serviceDateEnd = serviceDateStart.replace(day=calendar.monthrange(serviceDateStart.year, serviceDateStart.month)[1])
                            recurringDesc = "IaaS Monthly"
                    hourlyRecurringFee = 0
                    hours = 0

                # Special handling for storage
                if category == "storage_service_enterprise":
                    iops = getDescription("storage_tier_level", item["children"])
                    storage = getDescription("performance_storage_space", item["children"])
                    snapshot = getDescription("storage_snapshot_space", item["children"])
                    if snapshot == "":
                        description = storage + " " + iops + " "
                    else:
                        description = storage+" " + iops + " with " + snapshot
                elif category == "performance_storage_iops":
                    iops = getDescription("performance_storage_iops", item["children"])
                    storage = getDescription("performance_storage_space", item["children"])
                    description = storage + " " + iops
                elif category == "storage_as_a_service":
                    if item["hourlyFlag"]:
                        model = "Hourly"
                        for child in item["children"]:
                            if "hourlyRecurringFee" in child:
                                hourlyRecurringFee = hourlyRecurringFee + float(child['hourlyRecurringFee'])
                        if hourlyRecurringFee>0:
                            hours = round(float(recurringFee) / hourlyRecurringFee)
                        else:
                            hours = 0
                    else:
                        model = "Monthly"
                    space = getStorageServiceUsage('performance_storage_space', item["children"])
                    tier = getDescription("storage_tier_level", item["children"])
                    snapshot = getDescription("storage_snapshot_space", item["children"])
                    if space == "" or tier == "":
                        description = model + " File Storage"
                    else:
                        if snapshot == "":
                            description = model + " File Storage "+ space + " at " + tier
                        else:
                            snapshotspace = getStorageServiceUsage('storage_snapshot_space', item["children"])
                            description = model + " File Storage " + space + " at " + tier + " with " + snapshotspace
                elif category == "guest_storage":
                        imagestorage = getStorageServiceUsage("guest_storage_usage", item["children"])
                        if imagestorage == "":
                            description = description.replace('\n', " ")
                        else:
                            description = imagestorage
                else:
                    description = description.replace('\n', " ")


                if invoiceType == "NEW":
                    # calculate non pro-rated amount for use in forecast
                    daysInMonth = monthrange(invoiceDate.year, invoiceDate.month)[1]
                    daysLeft = daysInMonth - invoiceDate.day + 1
                    dailyAmount = recurringFee / daysLeft
                    NewEstimatedMonthly = dailyAmount * daysInMonth
                # Append record to dataframe
                row = {'Portal_Invoice_Date': invoiceDate.strftime("%Y-%m-%d"),
                       'Portal_Invoice_Time': invoiceDate.strftime("%H:%M:%S%z"),
                       'Service_Date_Start': serviceDateStart.strftime("%Y-%m-%d"),
                       'Service_Date_End': serviceDateEnd.strftime("%Y-%m-%d"),
                       'IBM_Invoice_Month': CFTSInvoiceDate,
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
                       'HourlyRate': round(hourlyRecurringFee,5),
                       'totalRecurringCharge': round(recurringFee,3),
                       'totalOneTimeAmount': float(totalOneTimeAmount),
                       'NewEstimatedMonthly': float(NewEstimatedMonthly),
                       'InvoiceTotal': float(invoiceTotalAmount),
                       'InvoiceRecurring': float(invoiceTotalRecurringAmount),
                       'Type': invoiceType,
                       'Recurring_Description': recurringDesc
                        }

                df = df.append(row, ignore_index=True)
    return df

def createReport(filename, classicUsage, paasUsage):
    # Write dataframe to excel
    logging.info("Creating Pivots File.")
    writer = pd.ExcelWriter(filename, engine='xlsxwriter')
    workbook = writer.book

    #
    # Write detail tab
    #
    classicUsage.to_excel(writer, 'Detail')
    usdollar = workbook.add_format({'num_format': '$#,##0.00'})
    worksheet = writer.sheets['Detail']
    worksheet.set_column('Q:V', 18, usdollar)
    totalrows,totalcols=classicUsage.shape
    worksheet.autofilter(0,0,totalrows,totalcols)

    #
    # Map Portal Invoices to SLIC Invoices / Create Top Sheet per SLIC month
    #

    classicUsage["totalAmount"] = classicUsage["totalOneTimeAmount"] + classicUsage["totalRecurringCharge"]

    months = classicUsage.IBM_Invoice_Month.unique()
    for i in months:
        logging.info("Creating top sheet for %s." % (i))
        ibminvoicemonth = classicUsage.query('IBM_Invoice_Month == @i')
        SLICInvoice = pd.pivot_table(ibminvoicemonth,
                                     index=["Type", "Portal_Invoice_Number", "Service_Date_Start", "Service_Date_End", "Recurring_Description"],
                                     values=["totalAmount"],
                                     aggfunc={'totalAmount': np.sum}, fill_value=0).sort_values(by=['Service_Date_Start'])

        out = pd.concat([d.append(d.sum().rename((k, ' ', ' ', 'Subtotal', ' '))) for k, d in SLICInvoice.groupby('Type')]).append(SLICInvoice.sum().rename((' ', ' ', ' ', 'Pay this Amount', '')))
        out.rename(columns={"Type": "Invoice Type", "Portal_Invoice_Number": "Invoice",
                            "Service_Date_Start": "Service Start", "Service_Date_End": "Service End",
                             "Recurring_Description": "Description", "totalAmount": "Amount"}, inplace=True)
        out.to_excel(writer, 'TopSheet-{}'.format(i))
        worksheet = writer.sheets['TopSheet-{}'.format(i)]
        format1 = workbook.add_format({'num_format': '$#,##0.00'})
        format2 = workbook.add_format({'align': 'left'})
        worksheet.set_column("A:E", 20, format2)
        worksheet.set_column("F:F", 18, format1)

    #
    # Build a pivot table by Invoice Type
    #
    if len(classicUsage)>0:
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

    if len(classicUsage)>0:
        categorySummary = pd.pivot_table(classicUsage, index=["Type", "Category", "Description"],
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
        paasUsage.to_excel(writer, "PaaS_Usage")
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
                                        columns=["invoiceMonth"],
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
                                     columns=["invoiceMonth"],
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

def accountUsage(IC_API_KEY, IC_ACCOUNT_ID, startdate, enddate):
    ##########################################################
    ## Get Usage for Account matching recuring invoice periods
    ##########################################################

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

    try:
        authenticator = IAMAuthenticator(IC_API_KEY)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        error = ("API exception {}.".format(str(e)))
        return accountUsage, error
    try:
        usage_reports_service = UsageReportsV4(authenticator=authenticator)
    except ApiException as e:
        logging.error("API exception {}.".format(str(e)))
        error = ("API exception {}.".format(str(e)))
        return accountUsage, error

    # PaaS consumption is delayed by one recurring invoice (ie April usage on June 1 recurring invoice)
    paasStart = startdate - relativedelta(months=1)
    paasEnd = enddate - relativedelta(months=2)

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
    parser.add_argument("-k", "--IC_API_KEY", default=os.environ.get('IC_API_KEY', None), metavar="apikey", help="IBM Cloud API Key")
    parser.add_argument("-s", "--startdate", default=os.environ.get('startdate', None), metavar="YYYY-MM", help="Start Year & Month in format YYYY-MM")
    parser.add_argument("-e", "--enddate", default=os.environ.get('enddate', None), metavar="YYYY-MM", help="End Year & Month in format YYYY-MM")
    parser.add_argument("--COS_APIKEY", default=os.environ.get('COS_APIKEY', None), help="COS apikey to use for Object Storage.")
    parser.add_argument("--COS_ENDPOINT", default=os.environ.get('COS_ENDPOINT', None), help="COS endpoint to use for Object Storage.")
    parser.add_argument("--COS_INSTANCE_CRN", default=os.environ.get('COS_INSTANCE_CRN', None), help="COS Instance CRN to use for file upload.")
    parser.add_argument("--COS_BUCKET", default=os.environ.get('COS_BUCKET', None), help="COS Bucket name to use for file upload.")
    parser.add_argument("--output", default=os.environ.get('output', 'invoice-analysis.xlsx'), help="Filename Excel output file. (including extension of .xlsx)")
    parser.add_argument("--SL_PRIVATE", default=False, action=argparse.BooleanOptionalAction, help="Use IBM Cloud Classic Private API Endpoint")
    args = parser.parse_args()

    if args.startdate == None or args.enddate == None:
        logging.error("You must provide a start and end month in the format of YYYY-MM.")
        quit()
    if args.IC_API_KEY == None:
        logging.error("You must provide an IBM Cloud ApiKey with billing View authority to run script.")
        quit()

    IC_API_KEY = args.IC_API_KEY

    # Calculate invoice dates based on SLIC invoice cutoffs.
    startdate, enddate = getInvoiceDates(args.startdate, args.enddate)

    # Change endpoint to private Endpoint if command line open chosen
    if args.SL_PRIVATE:
        SL_ENDPOINT = "https://api.service.softlayer.com/xmlrpc/v3.1"
    else:
        SL_ENDPOINT = "https://api.softlayer.com/xmlrpc/v3.1"

    #  Retrieve Invoices from classic
    classicUsage = getInvoiceDetail(IC_API_KEY, SL_ENDPOINT, startdate, enddate)

    # Retrieve Usage from IBM Cloud
    IC_ACCOUNT_ID = getAccountId(IC_API_KEY)

    paasUsage = accountUsage(IC_API_KEY, IC_ACCOUNT_ID, startdate, enddate)

    # Build Exel Report
    createReport(args.output, classicUsage, paasUsage)

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
