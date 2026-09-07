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
        continue

      cols = row.find_all("td")
      if not cols:
          continue
          
      # --- ADDITIONAL MEETING ROW DETECTION ---
      first_col = cols[0]
      # Check if this row is the indicator for an additional meeting time
      if first_col.get("colspan") == "5" and current_section_elem is not None:
          try:
              # Indices shift by 4 because 5 columns are merged into the first index (5 - 1 = 4)
              # Original days was 7 -> now 3
              # Original time was 12 -> now 8
              # Original location was 13 -> now 9
              # Original date was 19 -> now 15
              meet_days = cols[6].get_text(strip=True)
              meet_time = cols[8].get_text(strip=True)
              meet_loc = cols[9].get_text(strip=True)
              meet_date = cols[11].get_text(strip=True)
              
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
          continue # Move to the next row since we finished handling the additional meeting

      # --- PRIMARY SECTION DATA ROW ---
      # Ensure there are enough columns to support your updated custom indices (weeks is at 20)
      if len(cols) > 20 and current_course_elem is not None:
        status = cols[0].get_text(strip=True)
        im = cols[1].get_text(strip=True)
        
        # --- CRN and Link Extraction ---
        crn = cols[3].get_text(strip=True)
        crn_link = ""
        crn_anchor = cols[3].find("a")
        if crn_anchor and "href" in crn_anchor.attrs:
            raw_href = crn_anchor["href"]
            # Extract just the URL part from JavaScript:winOpen('URL')
            if "winOpen('" in raw_href:
                crn_link = raw_href.split("winOpen('")[1].split("')")[0]
            else:
                crn_link = raw_href
                
        cred = cols[4].get_text(strip=True)
        days = cols[7].get_text(strip=True)
        time_slot = cols[12].get_text(strip=True)
        
        location = cols[13].get_text(strip=True)
        instructor = cols[18].get_text(strip=True)
        date = cols[19].get_text(strip=True)
        weeks = cols[20].get_text(strip=True)

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

    # 6. Export formatted XML tree to file
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write("classes.xml", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
  asyncio.run(run_scraper())
