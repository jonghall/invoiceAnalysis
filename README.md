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
   - The following excel tabs will only exist if there are servers of these types on the analyzed invoices
        - ***HrlyVirtualServerPivot*** tab is a pivot of just Hourly Classic VSI's
        - ***MnthlyVirtualServerPivot*** tab is a pivot of just monthly Classic VSI's
        - ***HrlyBareMetalServerPivot*** tab is a pivot of Hourly Bare Metal Servers
        - ***MnthlyBareMetalServerPivot*** tab is a pivot table of monthly Bare Metal Server

Instructions:

1. Install required packages.  
````
pip install -r requirements.txt
````
2.  Set environment variables.
```bazaar
export SL_API_USERNAME=IBMxxxxx
export SL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxx
```

3.  Run Python script.
```bazaar
python invoiceAnalysis.py -s 2021/01 -e 2021/06 --output analysis_JanToMay.XLSX
```

```bazaar
usage: invoiceAnalysis.py [-h] [-u USERNAME] [-k APIKEY] [-s STARTDATE] [-e ENDDATE] [--output OUTPUT] [--COS_ENDPOINT COS_ENDPOINT] [--COS_APIKEY COS_APIKEY] [--COS_INSTANCE_CRN COS_INSTANCE_CRN] [--COS_BUCKET COS_BUCKET]

Export detail from invoices between dates sorted by Hourly vs Monthly between Start and End date.

optional arguments:
  -h, --help            show this help message and exit
  -u USERNAME, --username USERNAME
                        IBM Cloud Classic API Key Username
  -k APIKEY, --apikey APIKEY
                        IBM Cloud Classic API Key
  -s STARTDATE, --startdate STARTDATE
                        Start Year & Month in format YYYY/MM
  -e ENDDATE, --enddate ENDDATE
                        End Year & Month in format YYYY/MM
  --output OUTPUT       Filename Excel output file. (including extension of .xlsx)
  --COS_ENDPOINT COS_ENDPOINT
                        COS endpoint to use for Object Storage.
  --COS_APIKEY COS_APIKEY
                        COS apikey to use for Object Storage.
  --COS_INSTANCE_CRN COS_INSTANCE_CRN
                        COS Instance CRN to use for file upload.
  --COS_BUCKET COS_BUCKET
                        COS Bucket name to use for file upload.



```
