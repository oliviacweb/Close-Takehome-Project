# Close-Takehome-Project
This script connects to the Close CRM API to import a list of companies and
contacts from a CSV file, then pulls them back out filtered by a founding date
range, and saves a breakdown by US state to a CSV report. Built as part of a
take-home project using Python and Close's REST API.


## What it does

The script runs in three parts, one after another:

**1. Import** <b>
Reads a CSV of companies and contacts, cleans up the data, and uploads
everything to Close. Each company becomes a lead in Close, and each contact
row gets attached to its lead.

**2. Search**<br>
Goes back into Close and pulls all the leads out, then filters down to only
the ones whose founding date falls between the start and end dates you give
it when you run the script.

**3. Report**<br>
Takes those filtered leads, groups them by US state, and writes a summary
CSV with stats for each state.

## How I dealt with the messy data

The CSV had a lot of issues throughout. Mixed up letter casing, phone numbers
with emoji in them, emails missing an @ sign, revenue written as
"$1,231,970.94" with a dollar sign and commas. Here is how each problem gets
handled:

**Names**<b>
Anything in the Contact Name column gets run through Python's `.title()` method,
which converts things like "jOHN dOE" to "John Doe" automatically.

**Emails**<br>
Each email gets checked against regex that looks for the
basic structure of a legitimate email address: characters, then @, then a domain,
then a dot, then at least two letters. Anything that does not fit gets skipped
with a warning printed to the terminal. Some cells also had two or three emails
separated by commas, semicolons, or line breaks, so the script splits those
apart before validating.

**Phone numbers**<br>
Before validating, the script strips out any characters that are not a plus
sign, digit, dash, or space. This saves numbers that had things like emoji
prefixes attached to them from being skipped. After stripping, a valid phone has to start with plus sign and be at least 6 characters long. Values like "unknown" and "+123"
get rejected.

**Revenue**<br>
The dollar sign and any commas get stripped out first, then the value gets
converted to a number. So "$2,777,611.57" becomes 2777611.57.

**Dates**<br>
The CSV uses DD.MM.YYYY format like "17.05.1987" which Python does not read
automatically. The script parses it into a proper date
object.

**Rows with no company name**<br>
Skipped entirely because without a company name there is no way to know which lead
to attach the contact to, and Close requires every contact to be linked to
a lead.

**Contacts with nothing usable**<br>

If a row has no name, no email, and no phone, there is nothing worth saving
so it gets skipped. But if even one of those has a value the contact is kept.
A name with no contact details is still kept and potentially useful.
<img width="785" height="231" alt="Screenshot 2026-03-11 at 3 35 39 PM" src="https://github.com/user-attachments/assets/cc7ad6eb-f966-4f70-92f1-3e9fd64edc5b" />

## How contacts get grouped into leads

In Close, a lead is the company record. One lead can have multiple contacts
under it. Since the CSV has one row per contact, the script first reads through
every row and groups them into a dictionary by company name. So all the Digitube
rows end up together, all the Blogpad rows together etc.

Then for each company it creates the lead in Close first, captures the ID that
Close sends back, and uses that ID to attach each contact to the right lead.
Close uses the ID to know which folder to file each contact under.

<img width="588" height="749" alt="Screenshot 2026-03-11 at 3 40 22 PM" src="https://github.com/user-attachments/assets/eb650639-3e05-4483-a07f-4ea9957faaf6" />

## How leads get filtered by date range

When you run the script you pass in two dates, a start and an end. The script
fetches all the leads from Close and checks each ones Company Founded date.
If it falls between those two dates the lead is kept. If not it gets ignored.

Close only returns 100 leads per response, so if there are more than 100 the
script keeps asking for the next batch until Close says there are no more. This
is called pagination and it means the script works at scale not just for small test data.
<img width="575" height="155" alt="Screenshot 2026-03-11 at 3 46 47 PM" src="https://github.com/user-attachments/assets/3afb7518-cd83-4843-87e8-fdba93709581" />

## State breakdown and revenue stats

Once the filtered leads are ready, the script groups them by US state. For
each state it figures out:

- How many leads are in that state
- Which lead has the highest revenue
- The total revenue added up across all leads in that state
- The median revenue across all leads in that state

The results get saved to a file called report.csv with states listed
alphabetically. Any leads with no state value get grouped under "Unknown" so
they show up in the report rather than being dropped.

<img width="685" height="267" alt="Screenshot 2026-03-10 at 10 08 19 PM" src="https://github.com/user-attachments/assets/b11d50f8-37f7-485a-bca9-9203d1eacfb5" />

## Dependencies

You need two libraries installed before running the script:

```bash
pip3 install requests python-dotenv
```

**requests** handles sending HTTP requests

**python-dotenv** reads the API key from the .env file so you do not have to
type it into the terminal every time.

## Setup

**1. Clone the repository**

**2. Get a Close API key**

Log into Close, go to Settings > Developer and generate a new key.
<img width="1292" height="383" alt="Screenshot 2026-03-10 at 10 13 14 PM" src="https://github.com/user-attachments/assets/4c82c37a-f4fa-4a83-b63d-6814be0f4e05" />


**3. Create your .env file**

In the project folder, create a file called .env and add this one line:

```
CLOSE_API_KEY=your_key_here
```

This keeps your key out of the code and out of GitHub. Never paste it directly
into the script or into a terminal command for security.

**4. Add your CSV**

Put your contacts CSV in the same folder as the script and name it
contacts.csv.

**5. Install the dependencies listed above**

**6. Run it**

use whichever date range you want, this is an example.

```bash
python3 close_import.py --start 1960-01-01 --end 2000-12-31
```
## Running the script details

**Full run, imports the data and generates the report:**<br>
```bash
python3 close_import.py --start 1960-01-01 --end 2000-12-31
```

**If the data is already in Close and you just want to re-run the report:**<br>
```bash
python3 close_import.py --start 1960-01-01 --end 2000-12-31 --skip-import
```

**To save the report under a different filename:**
```bash
python3 close_import.py --start 1960-01-01 --end 2000-12-31 --output my_report.csv
```

The start and end dates can be anything in YYYY-MM-DD format. Changing them
and re-running with --skip-import is a quick way to explore different date
windows without re-uploading all the data.

