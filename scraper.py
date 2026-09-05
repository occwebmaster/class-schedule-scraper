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
    await page.select_option('select[name="sel_ptrm"]', "4")

    # Subject -> "%" (<all>)
    await page.select_option('select[name="sel_subj"]', "%")

    # Open Classes Only -> "Y" (handles both radio button or dropdown implementations)
    oo_radio = page.locator('input[name="oo"][value="Y"]')
    if await oo_radio.count() > 0:
      await oo_radio.check()
    else:
      await page.select_option('select[name="oo"]', "Y")

    # 3. Submit the search form
    await page.click('input[type="submit"]')

    # Wait for the results table to appear in the DOM
    await page.wait_for_selector("table", timeout=60000)

    # 4. Get rendered HTML content
    html_content = await page.content()
    await browser.close()

    # 5. Parse HTML and build XML structure
    soup = BeautifulSoup(html_content, "html.parser")
    root = ET.Element("schedule", term="OCC Fall 2026")

    current_subject_elem = None
    current_course_elem = None

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

      # Section data rows
      cols = row.find_all("td")
      if len(cols) >= 15 and current_course_elem is not None:
        status = cols[0].get_text(strip=True)
        im = cols[1].get_text(strip=True)
        zc = "true" if "[Z]" in cols[2].get_text(strip=True) else "false"
        crn = cols[3].get_text(strip=True)
        cred = cols[4].get_text(strip=True)
        days = cols[5].get_text(strip=True)
        time_slot = cols[6].get_text(strip=True)
        location = cols[7].get_text(strip=True)
        cap = cols[8].get_text(strip=True)
        act = cols[9].get_text(strip=True)
        wl_cap = cols[10].get_text(strip=True)
        wl_act = cols[11].get_text(strip=True)
        instructor = cols[12].get_text(strip=True)
        date = cols[13].get_text(strip=True)
        weeks = cols[14].get_text(strip=True)

        if crn:  # New section row
          section = ET.SubElement(
              current_course_elem,
              "section",
              status=status,
              im=im,
              zc=zc,
              crn=crn,
              cred=cred,
              cap=cap,
              act=act,
              wl_cap=wl_cap,
              wl_act=wl_act,
              instructor=instructor,
              date=date,
              weeks=weeks,
          )
          ET.SubElement(
              section,
              "meeting",
              days=days,
              time=time_slot,
              location=location,
          )

    # 6. Export formatted XML tree to file
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write("classes.xml", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
  asyncio.run(run_scraper())
