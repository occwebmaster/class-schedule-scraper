import asyncio
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


async def run_scraper():
  async with async_playwright() as p:
    # Launch headless browser
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()

    # 1. Navigate to CCCD schedule search page
    search_url = "https://ssb-prod.ec.cccd.edu/PROD/pw_pub_sched.p_search?Term=202670&college=OC"
    await page.goto(search_url, wait_until="networkidle")

    # 2. Select filter parameters
    # Part of Term -> "4" (Non Full Term)
    await page.select_option('select[name="sel_ptrm"]', '4')

    # Subject -> "%" (<all>)
    await page.select_option('select[name="sel_subj"]', '%')

    # Open Classes Only -> "Y"
    oo_radio = page.locator('input[name="oo"][value="Y"]')
    if await oo_radio.count() > 0:
      await oo_radio.check()
    else:
      await page.select_option('select[name="oo"]', 'Y')

    # 3. Submit the search form (Click visible submit button)
    await page.click('input[type="submit"]:visible')

    # Wait for the results table to appear in the DOM
    await page.wait_for_selector("table", timeout=50000)

    # 4. Get rendered HTML content
    html_content = await page.content()
    await browser.close()

    # 5. Parse HTML and build XML structure
    soup = BeautifulSoup(html_content, "html.parser")
    root = ET.Element("schedule", term="OCC Fall 2026")

    current_subject_elem = None
    current_course_elem = None
    current_section_elem = None

    # Parse rows from the schedule table
    for row in soup.find_all("tr"):
      # Subject header rows
      subj_td = row.find("td", class_="subject_header")
      if subj_td:
        current_subject_elem = ET.SubElement(
            root, "subject", name=subj_td.get_text(strip=True)
        )
        continue

      # Course header rows
      crn_td = row.find("td", class_="crn_header")
      if crn_td and current_subject_elem is not None:
        current_course_elem = ET.SubElement(
            current_subject_elem, "course", name=crn_td.get_text(strip=True)
        )
        # CRUCIAL FIX: Reset the active section when a new course starts
        # This prevents meetings from bleeding into the previous course
        current_section_elem = None 
        continue

      cols = row.find_all("td")
      if not cols:
          continue
          
      first_col = cols[0]
      
      # Determine if this row is a primary section row by checking if col[3] is a numeric CRN
      crn_text = cols[3].get_text(strip=True) if len(cols) > 3 else ""
      is_primary_row = bool(crn_text.isdigit())
      
      # --- PRIMARY SECTION DATA ROW ---
      if is_primary_row and current_course_elem is not None:
        status = cols[0].get_text(strip=True)
        im = cols[1].get_text(strip=True)
        crn = crn_text
        
        # --- CRN Link Extraction ---
        crn_link = ""
        crn_anchor = cols[3].find("a")
        if crn_anchor and "href" in crn_anchor.attrs:
            raw_href = crn_anchor["href"]
            if "winOpen('" in raw_href:
                crn_link = raw_href.split("winOpen('")[1].split("')")[0]
            else:
                crn_link = raw_href
                
        cred = cols[4].get_text(strip=True) if len(cols) > 4 else ""
        
        # Identify if this row matches the colspan="8" format for timeslots (e.g. TBA)
        is_primary_colspan_8 = (len(cols) > 5 and cols[5].get("colspan") == "8")
        
        if is_primary_colspan_8:
            days = ""
            time_slot = cols[5].get_text(strip=True)
            location = cols[6].get_text(strip=True) if len(cols) > 6 else ""
            instructor = cols[11].get_text(strip=True) if len(cols) > 11 else ""
            date = cols[12].get_text(strip=True) if len(cols) > 12 else ""
            weeks = cols[13].get_text(strip=True) if len(cols) > 13 else ""
        else:
            # Gather standard days from columns 5 to 11
            days_list = [cols[i].get_text(strip=True) for i in range(5, 12) if i < len(cols) and cols[i].get_text(strip=True)]
            days = " ".join(days_list)
            
            time_slot = cols[12].get_text(strip=True) if len(cols) > 12 else ""
            location = cols[13].get_text(strip=True) if len(cols) > 13 else ""
            instructor = cols[18].get_text(strip=True) if len(cols) > 18 else ""
            date = cols[19].get_text(strip=True) if len(cols) > 19 else ""
            weeks = cols[20].get_text(strip=True) if len(cols) > 20 else ""

        if crn:  # New section row
          current_section_elem = ET.SubElement(
              current_course_elem,
              "section",
              status=status,
              im=im,
              crn=crn,
              crn_link=crn_link,
              cred=cred,
              instructor=instructor,
              date=date,
              weeks=weeks,
          )
          # Initial meeting element attached to the section
          ET.SubElement(
              current_section_elem,
              "meeting",
              days=days,
              time=time_slot,
              location=location,
              date=date
          )

      # --- ADDITIONAL MEETING ROW DETECTION ---
      elif first_col.get("colspan") == "5" and current_section_elem is not None:
          try:
              # Check for the secondary meeting colspan="8" edge-case
              is_addl_colspan_8 = (len(cols) > 1 and cols[1].get("colspan") == "8")
              
              if is_addl_colspan_8:
                  meet_time = cols[1].get_text(strip=True)
                  meet_days = ""
                  meet_loc = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                  meet_date = cols[4].get_text(strip=True) if len(cols) > 4 else ""
              else:
                  # Gather standard days from columns 1 to 7
                  meet_days_list = [cols[i].get_text(strip=True) for i in range(1, 8) if i < len(cols) and cols[i].get_text(strip=True)]
                  meet_days = " ".join(meet_days_list)
                  meet_time = cols[8].get_text(strip=True) if len(cols) > 8 else ""
                  meet_loc = cols[9].get_text(strip=True) if len(cols) > 9 else ""
                  meet_date = cols[11].get_text(strip=True) if len(cols) > 11 else ""
              
              ET.SubElement(
                  current_section_elem,
                  "meeting",
                  days=meet_days,
                  time=meet_time,
                  location=meet_loc,
                  date=meet_date
              )
          except IndexError:
              continue

    # 6. Export formatted XML tree to file
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write("classes.xml", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
  asyncio.run(run_scraper())
