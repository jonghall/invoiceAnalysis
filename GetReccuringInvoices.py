__author__ = 'jonhall'
#
## Get Current Invoices
## Place APIKEY & Username in config.ini
## or pass via commandline  (example: GetRecurringInvoices.py -u=userid -k=apikey)
##

import sys, getopt, socket, SoftLayer, json, string, configparser, os, argparse



def initializeSoftLayerAPI():
    ## READ CommandLine Arguments and load configuration file
    parser = argparse.ArgumentParser(description="Print a report of Recurring invoices sorted by Hourly vs Monthly between Start and End date.")
    parser.add_argument("-u", "--username", help="SoftLayer API Username")
    parser.add_argument("-k", "--apikey", help="SoftLayer APIKEY")
    parser.add_argument("-c", "--config", help="config.ini file to load")

    args = parser.parse_args()

    if args.config != None:
        filename=args.config
    else:
        filename="config.ini"

    if (os.path.isfile(filename) is True) and (args.username == None and args.apikey == None):
        ## Read APIKEY from configuration file
        config = configparser.ConfigParser()
        config.read(filename)
        client = SoftLayer.Client(username=config['api']['username'], api_key=config['api']['apikey'])
    else:
        ## Read APIKEY from commandline arguments
        if args.username == None and args.apikey == None:
            print ("You must specify a username and APIkey to use.")
            quit()
        if args.username == None:
            print ("You must specify a username with your APIKEY.")
            quit()
        if args.apikey == None:
            print("You must specify a APIKEY with the username.")
            quit()
        client = SoftLayer.Client(username=args.username, api_key=args.apikey)
    return client


#
# Get APIKEY from config.ini & initialize SoftLayer API
#

client = initializeSoftLayerAPI()


#
# GET LIST OF INVOICES
#
print ()

startdate=input("Report Start Date (MM/DD/YYYY): ")
enddate=input("Report End Date (MM/DD/YYYY): ")


print()
print("Looking up invoices....")

topLevelCategories = client['Product_Item_Category'].getTopLevelCategories()

# Build Filter for Invoices
InvoiceList = client['Account'].getInvoices(filter={
        'invoices': {
            'createDate': {
                'operation': 'betweenDate',
                'options': [
                     {'name': 'startDate', 'value': [startdate+" 0:0:0"]},
                     {'name': 'endDate', 'value': [enddate+" 23:59:59"]}

                ]
            },
                    }
        })


print ()
print ('{:<35} {:<30} {:>8} {:>16} {:>16} {:>16} {:<15}'.format("Invoice Date /", "Invoice Number /", "Hours", "Hourly Rate", "Recurring Charge",  "Invoice Amount", "Type"))
print ('{:<35} {:<30} {:>8} {:>16} {:>16} {:>16} {:<15}'.format("Hostname      ", "Description     ", "     ", "           ", "                ",  "              ", "    "))
print ('{:<35} {:<30} {:>8} {:>16} {:>16} {:>16} {:<15}'.format("==============", "================", "=====", "===========", "================",  "==============", "===="))
for invoice in InvoiceList:
    if invoice['typeCode'] == "RECURRING":
        invoiceID = invoice['id']
        Billing_Invoice = client['Billing_Invoice'].getObject(id=invoiceID, mask="invoiceTopLevelItemCount,invoiceTopLevelItems,invoiceTotalAmount, invoiceTotalOneTimeAmount, invoiceTotalRecurringAmount")
        if Billing_Invoice['invoiceTotalAmount'] > "0":
            # PRINT INVOICE SUMMARY LINE
            print ('{:35} {:<30} {:>8} {:>16} {:>16,.2f} {:>16,.2f} {:<15}'.format(Billing_Invoice['createDate'][0:10], Billing_Invoice['id'], " ", " ", float(Billing_Invoice['invoiceTotalAmount']), float(Billing_Invoice['invoiceTotalRecurringAmount']), Billing_Invoice['typeCode']))

            print ()
            print ("** ACTUAL HOURLY USAGE INVOICED IN ARREARS")
            print ()
            # ITERATE THROUGH DETAIL SELECTING HOURLY ITEMS
            hourlyRecurringTotal = 0
            totalHours = 0
            totalItems = 0
            maxHours = 0
            maxRecurringFee = 0
            minHours = 999999
            minRecurringFee = 0
            for item in Billing_Invoice['invoiceTopLevelItems']:
                associated_children = client['Billing_Invoice_Item'].getAssociatedChildren(id=item['id'])

                if 'hourlyRecurringFee' in item:
                    recurringFee = float(item['recurringFee'])
                    hourlyRecurringFee = float(item['hourlyRecurringFee'])
                    hours = round(float(item['recurringFee']) / hourlyRecurringFee)

                    # SUM UP HOURLY CHARGE
                    for child in associated_children:
                        recurringFee = recurringFee + float(child['recurringFee'])
                        if 'hourlyRecurringFee' in child:
                            hourlyRecurringFee = hourlyRecurringFee + float(child['hourlyRecurringFee'])
                        else:
                            hourlyRecurringFee = 0

                    if 'hostName' in item:
                        hostName = item['hostName']+"."+item['domainName']
                    else:
                        hostName = "Unnamed Device"

                    #Lookup CategoryCode Description
                    category = item["categoryCode"]
                    for topLevel in topLevelCategories:
                        if topLevel['categoryCode'] == category:
                            category = topLevel['name']
                            quit
                    # PRINT LINE ITEM DETAIL FOR TOP LEVEL ITEM
                    print ('{:<35} {:<30} {:>8} {:>16,.3f} {:>16,.2f}'.format(hostName[0:35],category[0:30], hours, round(hourlyRecurringFee,3), round(recurringFee,2)))
                    if hours > maxHours:
                        maxHours = hours
                        maxRecurringFee = recurringFee

                    if hours < minHours:
                        minHours = hours
                        minRecurringFee = recurringFee

                    hourlyRecurringTotal = hourlyRecurringTotal + recurringFee
                    totalHours = totalHours + hours
                    totalItems = totalItems + 1
            print ()
            print ('{:<35} {:>20} Instances {:>8} {:>16} {:>16,.2f}'.format("Hourly Totals", totalItems, totalHours, " " , round(hourlyRecurringTotal,2)))
            print ('{:<35} {:<30} {:>8} {:>16} {:>16,.2f}'.format("Hourly Max"," ", minHours, " " , round(minRecurringFee,2)))
            print ('{:<35} {:<30} {:>8} {:>16} {:>16,.2f}'.format("Hourly Max"," ", maxHours, " " , round(maxRecurringFee,2)))
            print ('{:<35} {:<30} {:>8} {:>16} {:>16,.2f}'.format("Hourly Average"," ", totalHours/totalItems, " " , round(hourlyRecurringTotal/totalItems,2)))

            print ()
            print ("** MONTHLY & OTHER ITEMS INVOICED IN ADVANCE")
            print ()
            monthlyRecurringTotal = 0
            totalMonthlyItems = 0
            for item in Billing_Invoice['invoiceTopLevelItems']:
                associated_children = client['Billing_Invoice_Item'].getAssociatedChildren(id=item['id'])
                if 'hourlyRecurringFee' not in item and float(item['recurringFee'])>0:
                    recurringFee = float(item['recurringFee'])
                    hourlyRecurringFee = 0
                    hours = 0
                    for child in associated_children:
                        recurringFee = recurringFee + float(child['recurringFee'])

                    if 'hostName' in item:
                        hostName = item['hostName']+"."+item['domainName']
                    else:
                        hostName = "Unnamed Device"

                    #Lookup CategoryCode Description
                    category = item["categoryCode"]
                    for topLevel in topLevelCategories:
                        if topLevel['categoryCode'] == category:
                            category = topLevel['name']
                            quit
                    # PRINT LINE ITEM DETAIL FOR TOP LEVEL ITEM
                    monthlyRecurringTotal = monthlyRecurringTotal + recurringFee
                    totalMonthlyItems = totalMonthlyItems + 1
                    print ('{:<35} {:<30} {:>8} {:>16,.3f} {:>16,.2f}'.format(hostName[0:35], category[0:30], hours, round(hourlyRecurringFee,3), round(recurringFee,2)))
            print()
            print ()
            print ('{:<35} {:<30} {:>8} {:>16} {:>16,.2f}'.format("Monthly totals"," ", " ", " " , round(monthlyRecurringTotal,2)))
            print ()




