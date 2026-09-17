import re
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- FILTER WHITELISTS ---
SUBJECT_WHITELIST = {
    "ALH",
    "COUN",
}

COURSE_WHITELIST = {
    "ANTH C1001",
    "CIS A100",
    "CIS A111",
    "COUN A120",
    "COUN A125",
    "COUN A170",
    "COS A180",
    "FASH A102",
    "FBM A102",
    "FILM A100",
    "FN A170",
    "GEOL A105L",
    "KIN A203",
    "KIN A270",
    "LIB A103",
    "MTKG A115",
    "MUS A100",
    "MUS A105",
    "THEA A100"
}


def build_normalized_course_set(courses):
    """
    Normalizes course whitelist codes. OCC schedules use an 'A' prefix for course numbers
    (e.g., 'CIS A100'), while catalog lists may use 'CIS 100'. This set matches both formats.
    """
    norm_set = set()
    for course in courses:
        clean_course = course.strip().upper()
        norm_set.add(clean_course)
        
        # Match pattern: SUBJECT (optional 'A') NUMBER (optional suffix)
        m = re.match(r"^([A-Z]+)\s+(A?)(\d+.*)$", clean_course)
        if m:
            subj, alpha_a, rest = m.groups()
            if alpha_a == 'A':
                norm_set.add(f"{subj} {rest}")
            else:
                norm_set.add(f"{subj} A{rest}")
    return norm_set


async def run_scraper():
    normalized_subjects = {s.strip().upper() for s in SUBJECT_WHITELIST}
    normalized_courses = build_normalized_course_set(COURSE_WHITELIST)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1. Navigate to CCCD schedule search page
        search_url = "https://ssb-prod.ec.cccd.edu/PROD/pw_pub_sched.p_search?Term=202670&college=OC"
        await page.goto(search_url, wait_until="networkidle")

        # 2. Select filter parameters
        await page.select_option('select[name="sel_ptrm"]', '%')
        await page.select_option('select[name="sel_subj"]', '%')

        # Open Classes Only -> "Y"
        oo_radio = page.locator('input[name="oo"][value="Y"]')
        if await oo_radio.count() > 0:
            await oo_radio.check()
        else:
            await page.select_option('select[name="oo"]', 'Y')

        # 3. Submit search form
        await page.click('input[type="submit"]:visible')
        await page.wait_for_selector("table", timeout=50000)

        # 4. Get rendered HTML content
        html_content = await page.content()
        await browser.close()

        # 5. Get current time & parse HTML
        now_pdt = datetime.now(ZoneInfo("America/Los_Angeles"))
        formatted_pdt = now_pdt.strftime("%Y-%m-%d %H:%M:%S %Z")
        
        soup = BeautifulSoup(html_content, "html.parser")

        noncredit_pattern = re.compile(r"^\S+\s+[A-Za-z]?\d{3}N\b")

        subjects = []
        current_subject = None
        current_course = None
        current_section = None
        subject_is_whitelisted = False

        # Parse rows into temporary data structure
        for row in soup.find_all("tr"):
            if row.find("th"):
                continue

            # --- SUBJECT HEADER ROW ---
            subj_td = row.find("td", class_="subject_header")
            if subj_td:
                subj_text = subj_td.get_text(strip=True)
                subj_words = subj_text.split()
                subj_code = subj_words[0].upper() if subj_words else ""

                # Step A: Check if subject is whitelisted
                subject_is_whitelisted = subj_code in normalized_subjects

                current_subject = {
                    "name": subj_text,
                    "courses": []
                }
                subjects.append(current_subject)
                current_course = None
                current_section = None
                continue

            # --- COURSE HEADER ROW (crn_header) ---
            crn_td = row.find("td", class_="crn_header")
            if crn_td and current_subject is not None:
                crn_text = crn_td.get_text(strip=True)

                # Step B: Record course logic
                if subject_is_whitelisted:
                    # If subject matched, automatically record all courses under it
                    current_course = {
                        "name": crn_text,
                        "sections": []
                    }
                    current_subject["courses"].append(current_course)
                else:
                    # Subject did NOT match -> Check if course code matches COURSE_WHITELIST
                    # Robust extraction handles formats like "CIS A100", "CIS A100 - Intro", "CIS 100"
                    match = re.match(r"^([A-Za-z]+\s+[A-Za-z]?\d+[A-Za-z]?)", crn_text)
                    extracted_course_code = match.group(1).upper() if match else " ".join(crn_text.split()[:2]).upper()

                    if extracted_course_code in normalized_courses:
                        current_course = {
                            "name": crn_text,
                            "sections": []
                        }
                        current_subject["courses"].append(current_course)
                    else:
                        current_course = None

                current_section = None 
                continue

            cols = row.find_all("td")
            if not cols:
                continue
                
            first_col = cols[0]
            crn_text = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            is_primary_row = bool(crn_text.isdigit())
            
            # --- PRIMARY SECTION DATA ROW ---
            if is_primary_row and current_course is not None:
                cred = cols[4].get_text(strip=True) if len(cols) > 4 else ""
                course_name = current_course["name"]

                try:
                    is_zero_credit = float(cred) == 0.0
                except ValueError:
                    is_zero_credit = False

                if is_zero_credit and noncredit_pattern.search(course_name):
                    current_section = None
                    continue

                status = cols[0].get_text(strip=True)
                im = cols[1].get_text(strip=True)
                crn = crn_text
                
                crn_link = ""
                crn_anchor = cols[3].find("a")
                if crn_anchor and "href" in crn_anchor.attrs:
                    raw_href = crn_anchor["href"]
                    if "winOpen('" in raw_href:
                        crn_link = raw_href.split("winOpen('")[1].split("')")[0]
                    else:
                        crn_link = raw_href
                
                is_primary_colspan_8 = (len(cols) > 5 and cols[5].get("colspan") == "8")
                
                if is_primary_colspan_8:
                    days = ""
                    time_slot = cols[5].get_text(strip=True)
                    location = cols[6].get_text(strip=True) if len(cols) > 6 else ""
                    instructor = cols[11].get_text(strip=True) if len(cols) > 11 else ""
                    date = cols[12].get_text(strip=True) if len(cols) > 12 else ""
                    weeks = cols[13].get_text(strip=True) if len(cols) > 13 else ""
                else:
                    days_list = [cols[i].get_text(strip=True) for i in range(5, 12) if i < len(cols) and cols[i].get_text(strip=True)]
                    days = " ".join(days_list)
                    time_slot = cols[12].get_text(strip=True) if len(cols) > 12 else ""
                    location = cols[13].get_text(strip=True) if len(cols) > 13 else ""
                    instructor = cols[18].get_text(strip=True) if len(cols) > 18 else ""
                    date = cols[19].get_text(strip=True) if len(cols) > 19 else ""
                    weeks = cols[20].get_text(strip=True) if len(cols) > 20 else ""

                current_section = {
                    "status": status,
                    "im": im,
                    "crn": crn,
                    "crn_link": crn_link,
                    "cred": cred,
                    "instructor": instructor,
                    "date": date,
                    "weeks": weeks,
                    "meetings": [
                        {
                            "days": days,
                            "time": time_slot,
                            "location": location,
                            "date": date
                        }
                    ]
                }
                current_course["sections"].append(current_section)

            # --- ADDITIONAL MEETING ROW ---
            elif first_col.get("colspan") == "5" and current_section is not None:
                try:
                    is_addl_colspan_8 = (len(cols) > 1 and cols[1].get("colspan") == "8")
                    
                    if is_addl_colspan_8:
                        meet_time = cols[1].get_text(strip=True)
                        meet_days = ""
                        meet_loc = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                        meet_date = cols[4].get_text(strip=True) if len(cols) > 4 else ""
                    else:
                        meet_days_list = [cols[i].get_text(strip=True) for i in range(1, 8) if i < len(cols) and cols[i].get_text(strip=True)]
                        meet_days = " ".join(meet_days_list)
                        meet_time = cols[8].get_text(strip=True) if len(cols) > 8 else ""
                        meet_loc = cols[9].get_text(strip=True) if len(cols) > 9 else ""
                        meet_date = cols[11].get_text(strip=True) if len(cols) > 11 else ""
                    
                    current_section["meetings"].append({
                        "days": meet_days,
                        "time": meet_time,
                        "location": meet_loc,
                        "date": meet_date
                    })
                except IndexError:
                    continue

        # 6. Build final XML tree, pruning empty subjects
        root = ET.Element("schedule", term="OCC Fall 2026", current_time=formatted_pdt)

        for subj in subjects:
            valid_courses = [c for c in subj["courses"] if c["sections"]]
            if not valid_courses:
                continue

            subj_elem = ET.SubElement(root, "subject", name=subj["name"])
            for course in valid_courses:
                course_elem = ET.SubElement(subj_elem, "course", name=course["name"])
                for sec in course["sections"]:
                    sec_elem = ET.SubElement(
                        course_elem,
                        "section",
                        status=sec["status"],
                        im=sec["im"],
                        crn=sec["crn"],
                        crn_link=sec["crn_link"],
                        cred=sec["cred"],
                        instructor=sec["instructor"],
                        date=sec["date"],
                        weeks=sec["weeks"],
                    )
                    for meet in sec["meetings"]:
                        ET.SubElement(
                            sec_elem,
                            "meeting",
                            days=meet["days"],
                            time=meet["time"],
                            location=meet["location"],
                            date=meet["date"]
                        )

        # 7. Export XML tree
        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ")
        tree.write("classes.xml", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    asyncio.run(run_scraper())
