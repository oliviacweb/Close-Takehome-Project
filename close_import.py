#!/usr/bin/env python3

import csv, re, sys, argparse, statistics, requests, os
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv  

# Load the .env file from the same folder as this script.
load_dotenv()

# The base URL for Close API
# Source: https://developer.close.com/
BASE_URL = "https://api.close.com/api/v1"



#SETUP
# creates a resuable HTTP session so we don't need to make new re-auth on every request
# attaches API key to session here


def get_session(api_key):
    session = requests.Session()
    session.auth = (api_key, "")  # (username=api_key, password="")
    session.headers.update({"Content-Type": "application/json"})  # tells Close we're sending JSON
    return session


# DATA CLEANING HELPERS
# These small functions are each responsible for cleaning one type of data.
# They are called later inside the import section for every row of the CSV.

# NAME CLEANUP- strips white space, converts to Title Case, returns None if blank
def clean_name(name):
    return name.strip().title() if name and name.strip() else None


# EMAIL CLEANUP- strips white space, returns None if no email
#  if multiple splits them on comma, semicolon or new line, validates with regex
# returns list formatted the way Close expects it
def parse_emails(raw):
    if not raw or not raw.strip():
        return []
    email_regex = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
    results = []
    for part in re.split(r'[,;\n]+', raw):  # split on comma, semicolon, or newline
        e = part.strip()
        if email_regex.match(e):
            results.append({"email": e, "type": "office"})
        elif e:
            print(f"!! Skipping invalid email: '{e}'")
    return results


# PHONE CLEANUP- validates there is a number else returns NONE, validates number w regex, removes junk
# prints warning if it must skip an invalid number
# returns list formatted the way CLOSE expects it
def parse_phones(raw):
    if not raw or not raw.strip():
        return []
    phone_regex = re.compile(r'^\+[\d\-\s]{5,}$')
    results = []
    for part in re.split(r'\n+', raw):  # split on newlines for multi-phone cells
        p = part.strip()
        cleaned = re.sub(r'[^\+\d\-\s]', '', p).strip()  # strip emoji and other junk characters
        if phone_regex.match(cleaned):
            results.append({"phone": cleaned, "type": "office"})
        elif p:
            print(f"!! Skipping invalid phone: '{p}'")
    return results


# DATE CLEANUP- returns NONE if date is blank
# parses date string into python datetime object
# returns none if cant be parsed with printed warning
def parse_date(raw):
    if not raw or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), "%d.%m.%Y")
    except ValueError:
        print(f"!! Could not parse date: '{raw}'")
        return None

# REVENUE CLEANUP- Converts revenue string to Python float
# strips blank space, dollar sign, commas then returns float
# prints error and returns NONE if it can't be parsed
def parse_revenue(raw):
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        print(f"!! Could not parse revenue: '{raw}'")
        return None


# CUSTOM FIELDS SETUP
# Close CRM supports "custom fields" and we need 3 for 'Company Founded', 'Company Revenue', 'Company US State'
# Fetch all existing custom fields from close account and for each see if it already exists, if it does we grab ID
# If it doesn't we create and grab new ID, Close identified custom fields when we send data using field ID
# returns dict with custom fields and IDs
# Source: https://developer.close.com/resources/custom-fields/lead-custom-fields/

def get_or_create_custom_fields(session):
    print("\nChecking custom fields in Close...")
    resp = session.get(f"{BASE_URL}/custom_field/lead/")
    resp.raise_for_status()  # raises an error if the request failed

    # build a quick lookup dict-  {"Field Name": "field_id", ...}
    existing = {f["name"]: f["id"] for f in resp.json().get("data", [])}

    needed = {"Company Founded": "date", "Company Revenue": "number", "Company US State": "text"}
    field_ids = {}
    for name, ftype in needed.items():
        if name in existing:
            field_ids[name] = existing[name]
            print(f"  ✓ Found existing field: '{name}'")
        else:
            r = session.post(f"{BASE_URL}/custom_field/lead/", json={"name": name, "type": ftype})
            r.raise_for_status()
            field_ids[name] = r.json()["id"]
            print(f"  ✓ Created new field: '{name}'")
    return field_ids


# IMPORT CSV

# main imprt function woring in 2 passes
# PASS 1 - reads every row of CSV and groups by company name using dict, keys are company names
# values is list of contacts/rows for that company 
# Uses Python's defaultdict(list) here which automatically
# creates an empty list for any new key, so we don't have to check first.
# PASS 2 - Upload to Close
# for each comp lead we parse the shared fields from first row, POST lead to Close and get back new ID
# Loop through the rows for that company and POST each contact linked to lead via lead_id field
# Source for lead creation: https://developer.close.com/resources/leads/
# Source for contact creation: https://developer.close.com/resources/contacts/
def import_csv(session, csv_path, field_ids):
    #prints visual divider
    print("\n" + "=" * 55)
    print("SECTION 1: Importing CSV → Close CRM")
    print("=" * 55)

    leads_map = defaultdict(list)  # { "CompanyName": [row1, row2, ...], ... }

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            company = row.get("Company", "").strip()
            if not company:
                print("!! Skipping row — missing company name")
                continue
            leads_map[company].append(row)

    print(f"\nFound {len(leads_map)} unique companies in the CSV.\n")
    created_leads = created_contacts = 0

    for company, rows in leads_map.items():
        print(f"→ {company}  ({len(rows)} row(s))")

        # All contacts in a company share the same founded/revenue/state values,
        # so we only need to read these from the first row of the group.
        first      = rows[0]
        founded_dt = parse_date(first.get("custom.Company Founded", ""))
        revenue    = parse_revenue(first.get("custom.Company Revenue", ""))
        state      = first.get("Company US State", "").strip() or None

        # Build the custom fields dict using field IDs as keys (required by Close API)
        custom_data = {}
        if founded_dt:          custom_data[field_ids["Company Founded"]]  = founded_dt.strftime("%Y-%m-%d")
        if revenue is not None: custom_data[field_ids["Company Revenue"]]  = revenue
        if state:               custom_data[field_ids["Company US State"]] = state

        # POST the lead to Close — this creates the company record
        payload = {"name": company}
        if custom_data:
            payload["custom"] = custom_data
        lead_resp = session.post(f"{BASE_URL}/lead/", json=payload)
        if not lead_resp.ok:
            print(f"x Failed to create lead '{company}': {lead_resp.text}")
            continue
        lead_id = lead_resp.json()["id"]  # Close returns the new lead's ID in the response
        print(f"  ✓ Lead created (ID: {lead_id})")
        created_leads += 1

        # POST each contact, linking them to this lead via lead_id
        for row in rows:
            name   = clean_name(row.get("Contact Name", ""))
            emails = parse_emails(row.get("Contact Emails", ""))
            phones = parse_phones(row.get("Contact Phones", ""))

            # skip the row if there is nothing to save- no name, email, or phone
            if not name and not emails and not phones:
                print(f"!! Skipping empty contact row")
                continue

            c_resp = session.post(f"{BASE_URL}/contact/", json={
                "lead_id": lead_id,        # links this contact to the lead we just created
                "name":    name or "Unknown",
                "emails":  emails,
                "phones":  phones,
            })
            if c_resp.ok:
                created_contacts += 1
                print(f" ✓ Contact: {name or '(no name)'}")
            else:
                print(f" X Failed contact '{name}': {c_resp.text}")

    print(f"\n✅ Import done: {created_leads} leads, {created_contacts} contacts created.")



# FIND LEADS BY FOUNDED DATE RANGE
# Fetches all leads from Close and filters to those founded within the given range
# Pagination- Close's API returns a maximum of 100 leads per request. If you have more than
# 100 leads you need to make multiple requests
# we do this by incrementing a "_skip" counter, skip 0 for page 1, skip
# 100 for page 2 etc. We keep going until Close tells us "has_more: false".
# docs- https://developer.close.com/topics/pagination/

def find_leads_by_date_range(session, field_ids, start_str, end_str):
    print("\n" + "=" * 55)
    print(f"SECTION 2: Leads founded between {start_str} and {end_str}")
    print("=" * 55)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        end_dt   = datetime.strptime(end_str,   "%Y-%m-%d")
    except ValueError:
        print("x Dates must be in YYYY-MM-DD format (e.g. 1990-01-01)")
        sys.exit(1)

    founded_fid = field_ids["Company Founded"]
    revenue_fid = field_ids["Company Revenue"]
    state_fid   = field_ids["Company US State"]

    # Request only the fields we need makes the response smaller and faster
    # doc for _fields parameter- https://developer.close.com/topics/fields/
    fields_param = f"id,name,custom.{founded_fid},custom.{revenue_fid},custom.{state_fid}"

    all_leads, has_more, skip = [], True, 0
    print("\nFetching leads from Close (paginating through results)...")

    while has_more:  # keep requesting pages until Close says there are no more
        resp = session.get(f"{BASE_URL}/lead/", params={
            "_fields": fields_param,
            "_limit":  100,   # max allowed per page
            "_skip":   skip,  # how many leads to skip
        })
        resp.raise_for_status()
        data = resp.json()
        all_leads.extend(data.get("data", []))  # add this pages leads to our running list
        has_more = data.get("has_more", False)  # Close tells us if there are more pages
        skip += 100

    print(f"Total leads fetched from Close: {len(all_leads)}")

    # Filter leads keep only those with a founded date within the specified range
    matching = []
    for lead in all_leads:
        raw = lead.get(f"custom.{founded_fid}")
        if not raw:
            continue  # skip leads with no founded date at all
        try:
            if start_dt <= datetime.strptime(raw, "%Y-%m-%d") <= end_dt:
                matching.append(lead)
        except ValueError:
            continue  # skip leads with an unparseable date

    print(f"  Leads matching date range: {len(matching)}")
    return matching, revenue_fid, state_fid


# SEGMENT BY STATE AND GENERATE REPORT
  # Groups the matching leads by state and writesCSV report
  # We loop through all matching leads and add each one to a dict keyed by state.
  # use defaultdict so we don't need to manually check if a state
  # key exists yet as it's created automatically the first time we see that state
  # Leads with no state are grouped under "Unknown" rather than silently dropped

def generate_report(leads, revenue_fid, state_fid, output_path):
    print("\n" + "=" * 55)
    print("SECTION 3: Generating state report")
    print("=" * 55)

    state_groups = defaultdict(list)  

    for lead in leads:
        state   = lead.get(f"custom.{state_fid}") or "Unknown"
        rev_raw = lead.get(f"custom.{revenue_fid}")
        state_groups[state].append({
            "name":    lead.get("name", "Unnamed"),
            "revenue": float(rev_raw) if rev_raw else 0.0  # default 0 if missing
        })

    with open(output_path, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["State", "Total Leads", "Lead with Most Revenue", "Total Revenue", "Median Revenue"])

        for state in sorted(state_groups.keys()):  # sort states alphabetically
            group    = state_groups[state]
            revenues = [l["revenue"] for l in group]
            top_lead = max(group, key=lambda l: l["revenue"])  # find single highest-revenue lead

            writer.writerow([
                state,
                len(group),
                top_lead["name"],
                f"${sum(revenues):,.2f}",
                f"${statistics.median(revenues):,.2f}",
            ])
            print(f"  {state}: {len(group)} lead(s) | Top: {top_lead['name']} | Total: ${sum(revenues):,.2f}")

    print(f"\n✅ Report saved to: {output_path}")


# MAIN

def main():

    #entry point of the script. Reads command line flags
    parser = argparse.ArgumentParser(description="Close CRM Import & Report Tool")
    parser.add_argument("--csv",         default="contacts.csv", help="Path to contacts CSV (default: contacts.csv)")
    parser.add_argument("--start",       required=True,  help="Founded date range start (YYYY-MM-DD)")
    parser.add_argument("--end",         required=True,  help="Founded date range end (YYYY-MM-DD)")
    parser.add_argument("--output",      default="report.csv",   help="Output filename (default: report.csv)")
    parser.add_argument("--skip-import", action="store_true",    help="Skip Section 1 if data is already imported")
    args = parser.parse_args()

    # Load the API key from the .env file (must be in the same folder as this script)
    api_key = os.getenv("CLOSE_API_KEY")
    if not api_key:
        print("Error: CLOSE_API_KEY not found. Make sure your .env file exists and contains it.")
        sys.exit(1)

    session   = get_session(api_key)                 # create authenticated HTTP session
    field_ids = get_or_create_custom_fields(session) # make sure custom fields exist in Close

    if not args.skip_import:
        import_csv(session, args.csv, field_ids)
    else:
        print("Skipping import (--skip-import flag set)")

    matching_leads, revenue_fid, state_fid = find_leads_by_date_range(
        session, field_ids, args.start, args.end
    )

    if not matching_leads:
        print("warning: No leads found in that date range. Try a larger date range.")
        sys.exit(0)

    generate_report(matching_leads, revenue_fid, state_fid, args.output)
    print("All done!")



#  only run main() if this file is being executed directly. 
# If another Python file were to import this one, main() would not run automatically.
if __name__ == "__main__":
    main()
