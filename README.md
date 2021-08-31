**IBM Cloud Classic Infrastructure Billing API Scripts**

Script | Description
------ | -----------
invoiceAnalysis.py | Analyzes all invoices between two dates and creates excel reports.
requirements.txt | Package requirements
logging.json | LOGGER config used by script

*invoiceAnalysis.py* analyzes IBM Cloud Classic Infrastructure invoices between two dates and consolidates billing data into an
Excel worksheet for review.  Each tab has a breakdown based on:

   - ***Detail*** tab has every invoice item for analyzed invoices represented as one row each.  All invoice types are included, including CREDIT invoices.  This data is summarized on the following tabs.
   - ***InvoiceMap*** tab has a mapping of each portal invoice, portal invoice date, invoice type grouped by the IBM monthly invoice they are billed on.
   - ***InvoiceSummary*** tab is a pivot table of all the charges by product category & month for analyzed invoices. It also breaks out oneTime amounts vs Recurring invoices.
   - ***CategorySummary*** tab is another pivot of all recurring charges broken down by Category, sub category (for example specific VSI sizes)
   - The following Excel tabs will exist if there are servers of these types of resources on the analyzed invoices
     - ***HrlyVirtualServerPivot*** tab is a pivot of just Hourly Classic VSI's
     - ***MnthlyVirtualServerPivot*** tab is a pivot of just monthly Classic VSI's
     - ***HrlyBareMetalServerPivot*** tab is a pivot of Hourly Bare Metal Servers
     - ***MnthlyBareMetalServerPivot*** tab is a pivot table of monthly Bare Metal Server
   - The following Excel tabs will be created if you supply IC_API_KEY & IC_ACCOUNT
     - ***PaaS_Usage*** shows the complete list of billing items showing the usageMonth, InvoiceMonth, ServiceName, and Plan Name with billable charges for each unit associated with the server. 
     - ***PaaS_Summary*** shows the billing charges for each service consumed.  Note the columns represent the usage month, not billing month. 
     - ***PaaS_Plan_Summary*** show the additional level of detail for the billing charges for each service and plan consumed.  Note the columns represent the usage month, not billing month.


Instructions:

1. Install required packages.  
````
pip install -r requirements.txt
````
2.  Set environment variables. COS apikey is only required if you wish file to be written to COS, otherwise file will be written locally.
```bazaar
![env_variables.png](env_variables.png)
```

3.  Run Python script.
```bazaar
python invoiceAnalysis.py -s 2021-01 -e 2021-06
```

```bazaar
usage: invoiceAnalysis.py [-h] [-s STARTDATE] [-e ENDDATE] [--SL_USER SL_USER] [--SL_API_KEY SL_API_KEY] [--SL_PRIVATE | --no-SL_PRIVATE] [--output OUTPUT] [--COS_ENDPOINT COS_ENDPOINT] [--COS_APIKEY COS_APIKEY] [--COS_INSTANCE_CRN COS_INSTANCE_CRN] [--COS_BUCKET COS_BUCKET]
                          [--IC_ACCOUNT IC_ACCOUNT] [--IC_API_KEY IC_API_KEY] [--BILLING_ENDPOINT BILLING_ENDPOINT] [--IAM_ENDPOINT IAM_ENDPOINT]

Export detail to Excel file from all IBM Cloud Classic invoices types between two months.

optional arguments:
  -h, --help            show this help message and exit
  -s STARTDATE, --startdate STARTDATE
                        Start Year & Month in format YYYY/MM
  -e ENDDATE, --enddate ENDDATE
                        End Year & Month in format YYYY/MM
  --SL_USER SL_USER     IBM Cloud Classic API Key Username
  --SL_API_KEY SL_API_KEY
                        IBM Cloud Classic API Key
  --SL_PRIVATE, --no-SL_PRIVATE
                        Use IBM Cloud Classic Private API Endpoint (default: False)
  --output OUTPUT       Filename Excel output file. (including extension of .xlsx)
  --COS_ENDPOINT COS_ENDPOINT
                        COS endpoint to use for Object Storage.
  --COS_APIKEY COS_APIKEY
                        COS apikey to use for Object Storage.
  --COS_INSTANCE_CRN COS_INSTANCE_CRN
                        COS Instance CRN to use for file upload.
  --COS_BUCKET COS_BUCKET
                        COS Bucket name to use for file upload.
  --IC_ACCOUNT IC_ACCOUNT
                        IBM Cloud Account ID
  --IC_API_KEY IC_API_KEY
                        IBM Cloud API Key
  --BILLING_ENDPOINT BILLING_ENDPOINT
                        IBM Cloud Billing API endpoint.
  --IAM_ENDPOINT IAM_ENDPOINT
                        IBM Cloud IAM endpoint.

```
