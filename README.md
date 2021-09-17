**IBM Cloud Classic Infrastructure Billing API Scripts**

Script | Description
------ | -----------
invoiceAnalysis.py | Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.
requirements.txt | Package requirements
logging.json | LOGGER config used by script

*invoiceAnalysis.py* analyzes IBM Cloud Classic Infrastructure invoices between two dates and consolidates billing data into an
Excel worksheet for review.  Each tab has a breakdown based on:

   - ***Detail*** tab has every invoice item for analyzed invoices represented as one row each.  All invoice types are included, including CREDIT invoices.  This data is summarized on the following tabs.
   - ***InvoiceMap*** tab has a mapping of each portal invoice, portal invoice date, invoice type grouped by the IBM monthly invoice they are billed on.
   - ***InvoiceSummary*** tab is a pivot table of all the charges by product category & months of analyzed invoices. It also breaks out oneTime amounts vs Recurring invoices.
   - ***CategorySummary*** tab is another pivot of all recurring charges broken down by Category, sub category (for example specific VSI sizes or Bare metal server types)
   - The following Excel tabs will exist if there are servers of these types of resources on the analyzed invoices
     - ***HrlyVirtualServerPivot*** tab is a pivot of just Hourly Classic VSI's
     - ***MnthlyVirtualServerPivot*** tab is a pivot of just monthly Classic VSI's
     - ***HrlyBareMetalServerPivot*** tab is a pivot of Hourly Bare Metal Servers
     - ***MnthlyBareMetalServerPivot*** tab is a pivot table of monthly Bare Metal Server
   - The following Excel tabs will be created if there is PaaS usage during the period requested
     - ***PaaS_Usage*** shows the complete list of invoice items showing the usageMonth, InvoiceMonth, ServiceName, and Plan Name with billable charges for each unit associated with the service. 
     - ***PaaS_Summary*** shows the invoice charges for each PaaS service consumed.  Note the columns represent invoice month, not usage month unless overridden by --PAAS_USE_USAGE_MONTH 
     - ***PaaS_Plan_Summary*** show the additional level of detail for the invoice charges for each PaaS service and plan consumed.  Note the columns represent invoice month, not usage month unless overridden by --PAAS_USE_USAGE_MONTH 


Instructions:

1. Install required packages.  
````
pip install -r requirements.txt
````
2. Set environment variables which can be used.  IBM COS only required if file needs to be written to COS, otherwise file will be written locally.
![env_variables.png](env_variables.png)

3. Run Python script.
*Note script no longer requires IBM Cloud Classic API Keys to execute, and instead uses a single IBM Cloud API Key to access both classic invoices and IBM Cloud Usage.*

```bazaar
export IC_API_KEY=<ibm cloud apikey>
python invoiceAnalysis.py -s 2021-01 -e 2021-06
```

```bazaar
usage: invoiceAnalysis.py [-h] [-k apikey] [-s YYYY-MM] [-e YYYY-MM] [--COS_APIKEY COS_APIKEY] [--COS_ENDPOINT COS_ENDPOINT] [--COS_INSTANCE_CRN COS_INSTANCE_CRN] [--COS_BUCKET COS_BUCKET] [--output OUTPUT] [--SL_PRIVATE | --no-SL_PRIVATE] [--PAAS_USE_USAGE_MONTH | --no-PAAS_USE_USAGE_MONTH]

Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.

optional arguments:
  -h, --help            show this help message and exit
  -k apikey, --IC_API_KEY apikey
                        IBM Cloud API Key
  -s YYYY-MM, --startdate YYYY-MM
                        Start Year & Month in format YYYY-MM
  -e YYYY-MM, --enddate YYYY-MM
                        End Year & Month in format YYYY-MM
  --COS_APIKEY COS_APIKEY
                        COS apikey to use for Object Storage.
  --COS_ENDPOINT COS_ENDPOINT
                        COS endpoint to use for Object Storage.
  --COS_INSTANCE_CRN COS_INSTANCE_CRN
                        COS Instance CRN to use for file upload.
  --COS_BUCKET COS_BUCKET
                        COS Bucket name to use for file upload.
  --output OUTPUT       Filename Excel output file. (including extension of .xlsx)
  --SL_PRIVATE, --no-SL_PRIVATE
                        Use IBM Cloud Classic Private API Endpoint (default: False)
  --PAAS_USE_USAGE_MONTH, --no-PAAS_USE_USAGE_MONTH
                        Use actual PaaS usage month for pivots instead of IBM Invoice Month which matches IBM invoices. (default: False)



```
