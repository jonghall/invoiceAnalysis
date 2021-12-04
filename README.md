# IBM Cloud Classic Infrastructure Invoice Analysis Report
*invoiceAnalysis.py* collects IBM Cloud Classic Infrastructure NEW, RECURRING, and CREDIT invoices and PaaS Usage between months specified in the parameters consolidates the data into an Excel worksheet for billing and usage analysis. 
In addition to consolidation of the detailed data,  pivot tables are created in Excel tabs to assist with understanding account usage.

### Required Files
Script | Description
------ | -----------
invoiceAnalysis.py | Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.
requirements.txt | Package requirements
logging.json | LOGGER config used by script
Dockerfile | Docker Build file used by code engine to build container.


### Identity & Access Management Requirements
| APIKEY | Description | Min Access Permissions
| ------ | ----------- | ----------------------
| IBM Cloud API Key | API Key used to pull classic and PaaS invoices and Usage Reports. | IAM Billing Viewer Role
| COS API Key | API Key used to write output to specified bucket (if specified) | COS Bucket Write access to Bucket at specified Object Storage CRN.


### Output Description
One Excel worksheet is created with multiple tabs from the collected data (Classic Invoices & PaaS Usage between start and end month specified).   _Tabs are only be created if there are related resources on the collected invoices._

*Excel Tab Explanation*
   - ***Detail*** tab has every invoice item for all the collected invoices represented as one row each. For invoices with multiple items, each row represents one top level invoice item.  All invoice types are included, including CREDIT invoices.  The detail tab can be sorted or filtered to find specific dates, billing item id's, or specific services.  
   - ***TopSheet-YYYY-MM*** tab(s) map each portal invoice to their corresponding IBM CFTS invoice(s) they are billed on.  These tabs can be used to facilitate reconciliation.
   - ***InvoiceSummary*** tab is a pivot table of all the charges by product category & month by invoice type. This tab can be used to understand changes in month to month usage.
   - ***CategorySummary*** tab is a pivot of all recurring charges broken down by Category and sub category (for example specific VSI sizes or Bare metal server types) to dig deeper into month to month usage changes.
   - ***HrlyVirtualServerPivot*** tab is a pivot of just Hourly Classic VSI's if they exist
   - ***MnthlyVirtualServerPivot*** tab is a pivot of just monthly Classic VSI's if they exist
   - ***HrlyBareMetalServerPivot*** tab is a pivot of Hourly Bare Metal Servers if they exist
   - ***MnthlyBareMetalServerPivot*** tab is a pivot table of monthly Bare Metal Server if they exist
   - ***PaaS_Usage*** shows the complete list of PaaS Usage showing the usageMonth, InvoiceMonth, ServiceName, and Plan Name with billable charges for each unit associated with the service. 
   - ***PaaS_Summary*** shows the invoice charges for each PaaS service consumed.  Note the columns represent CFTS invoice month, not actual usage month.
   - ***PaaS_Plan_Summary*** show an additional level of detail for each PaaS service and plan consumed.  Note the columns represent CFTS invoice month, not actual usage month/

## Script Execution Instructions: _See alternate instructions for Code Engine._

1. Install required packages.  
````
pip install -r requirements.txt
````
2. Set environment variables which can be used.  IBM COS only required if file needs to be written to COS, otherwise file will be written locally.

|Parameter | Environment Variable | Default | Description
|--------- | -------------------- | ------- | -----------
|--IC_API_KEY, -k | IC_API_KEY | None | IBM Cloud API Key to be used to retrieve invoices and usage.
|--STARTDATE, -s | startdate | None | Start Month in YYYY-MM format
|--ENDDATE, -e | enddate | None | End Month in YYYY-MM format
|--months, -m | months | None | Number of months including last full month to include in report. (use instead of -s/-e)
|--COS_APIKEY | COS_APIKEY | None | COS API to be used to write output file to object storage, if not specified file written locally.
|--COS_BUCKET | COS_BUCKET | None | COS Bucket to be used to write output file to.
|--COS_ENDPOINT | COS_ENDPOINT| None | COS Endpoint to be used to write output file to.
|--OS_INSTANCE_CRN | COS_INSTANCE_CRN | None | COS Instance CRN to be used to write output file to.
|--sendGridApi | sendGridApi | None | SendGrid API key to use to send Email.
|--sendGridTo | sendGridTo | None | SendGrid comma delimited list of email addresses to send output report to.
|--sendGridFrom | sendGridFrom | None | SendGrid from email addresss to send output report from.
|--sendGridSubject | sendGridSubject | None | SendGrid email subject.
|--OUTPUT | OUTPUT | invoice-analysis.xlsx | Output file name used.
|--SL_PRIVATE,--no_SL_PRIVATE | | --no_SL_PRIVATE | Whether to use Public or Private Endpoint.

3. Run Python script (Python 3.9 required).</br>

```bazaar
export IC_API_KEY=<ibm cloud apikey>
python invoiceAnalysis.py -s 2021-01 -e 2021-06
```

```bazaar
usage: invoiceAnalysis.py [-h] [-k apikey] [-s YYYY-MM] [-e YYYY-MM] [-m MONTHS] [--COS_APIKEY COS_APIKEY] [--COS_ENDPOINT COS_ENDPOINT] [--COS_INSTANCE_CRN COS_INSTANCE_CRN] [--COS_BUCKET COS_BUCKET] [--sendGridApi SENDGRIDAPI]      ─╯
                          [--sendGridTo SENDGRIDTO] [--sendGridFrom SENDGRIDFROM] [--sendGridSubject SENDGRIDSUBJECT] [--output OUTPUT] [--SL_PRIVATE | --no-SL_PRIVATE]

Export usage detail by invoice month to an Excel file for all IBM Cloud Classic invoices and PaaS Consumption.

optional arguments:
  -h, --help            show this help message and exit
  -k apikey, --IC_API_KEY apikey
                        IBM Cloud API Key
  -s YYYY-MM, --startdate YYYY-MM
                        Start Year & Month in format YYYY-MM
  -e YYYY-MM, --enddate YYYY-MM
                        End Year & Month in format YYYY-MM
  -m MONTHS, --months MONTHS
                        Number of months including last full month to include in report.

  --COS_APIKEY COS_APIKEY
                        COS apikey to use for Object Storage.
  --COS_ENDPOINT COS_ENDPOINT
                        COS endpoint to use for Object Storage.
  --COS_INSTANCE_CRN COS_INSTANCE_CRN
                        COS Instance CRN to use for file upload.
  --COS_BUCKET COS_BUCKET
                        COS Bucket name to use for file upload.
  --sendGridApi SENDGRIDAPI
                        SendGrid ApiKey used to email output.
  --sendGridTo SENDGRIDTO
                        SendGrid comma deliminated list of emails to send output to.
  --sendGridFrom SENDGRIDFROM
                        Sendgrid from email to send output from.
  --sendGridSubject SENDGRIDSUBJECT
                        SendGrid email subject for output email
  --output OUTPUT       Filename Excel output file. (including extension of .xlsx)
  --SL_PRIVATE, --no-SL_PRIVATE
                        Use IBM Cloud Classic Private API Endpoint (default: False)


```

## Running IBM Cloud Classic Infrastructure Invoice Analysis Report as a Code Engine Job

### Setting up IBM Code Engine and building container to run report
1. Create project, build job and job.  
   1.1. Open the Code Engine console.  
   1.2. Select Start creating from Start from source code.  
   1.3. Select Job  
   1.4. Enter a name for the job such as invoiceanalysis. Use a name for your job that is unique within the project.  
   1.5. Select a project from the list of available projects of if this is the first one, create a new one. Note that you must have a selected project to deploy an app.  
   1.6. Enter the URL for this GitHub repository and click specify build details. Make adjustments if needed to URL and Branch name. Click Next.  
   1.7. Select Dockerfile for Strategy, Dockerfile for Dockerfile, 10m for Timeout, and Medium for Build resources. Click Next.  
   1.8. Select a container registry location, such as IBM Registry, Dallas.  
   1.9. Select Automatic for Registry access.  
   1.10. Select an existing namespace or enter a name for a new one, for example, newnamespace. 
   1.11. Enter a name for your image and optionally a tag.  
   1.12. Click Done.  
   1.13. Click Create.  
2. Create configmaps and secrets.  
   2.1. From project list, choose newly created project.  
   2.2. Select secrets and configmaps  
   2.3. click create, choose config map, and give it a name. Add the following key value pairs    
        ***COS_BUCKET*** = Bucket within COS instance to write report file to.  
        ***COS_ENDPOINT*** = Public COS Endpoint for bucket to write report file to  
        ***COS_INSTANCE_CRN*** = COS Service Instance CRN in which bucket is located.  
   2.4. Select secrets and configmaps (again)
   2.5.  click create, choose secrets, and give it a name. Add the following key value pairs  
         ***IC_API_KEY*** = an IBM Cloud API Key with Billing access to IBM Cloud Account  
         ***COS_APIKEY*** = your COS Api Key Id with writter access to appropriate bucket  
3. Choose the job previously created.  
   3.1. Click on the Environment variables tab.   
   3.2. Click add, choose reference to full configmap, and choose configmap created in previous step and click add.  
   3.3. Click add, choose reference to full secret, and choose secrets created in previous step and click add.  
   3.4 .Click add, choose literal value (click add after each, and repeat)  
         ***startdate*** = start year & month of invoice analysis in YYYY-MM format  
         ***enddate*** = end year & month invoice analysis in YYYY-MM format  
         ***output*** = report filename (including extension of XLSX to be written to COS bucket)  
4. to Run report click ***Submit job***  
5. Logging for job can be found from job screen, by clicking Actions, Logging
