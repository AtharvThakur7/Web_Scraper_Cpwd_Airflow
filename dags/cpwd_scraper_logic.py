from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, UnexpectedAlertPresentException
import pandas as pd
import time
from bs4 import BeautifulSoup
import json 


CHROMEDRIVER_PATH = "/usr/local/bin/chromedriver"
REQUIRED_TENDER_COUNT = 20

# renaming my cols used in transformation
CSV_COLS_MAP = {
    "NIT/RFP NO": "ref_no",
    "Name of Work / Subwork / Packages": "title",
    "Estimated Cost": "tender_value",
    "Bid Submission Closing Date & Time": "bid_submission_end_date",
    "EMD Amount": "emd",
    "Bid Opening Date & Time": "bid_open_date"
}

def extract_tender_data() -> list[dict]:
    
    driver = None
    tender_data_raw = []
    try:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--headless") 
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox") 
        chrome_options.add_argument("--disable-dev-shm-usage") 

        service = Service(executable_path=CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.get("https://etender.cpwd.gov.in/")
        time.sleep(3)

        
        try:
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            print("Alert detected: ", alert.text)
            alert.accept()
            time.sleep(3)
        except TimeoutException:
            print("No initial alert detected.")
        except Exception as e:
            print(f"Error handling initial alert: {e}")

        new_tenders_tab = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//a[normalize-space()='New Tenders']"))
        )
        new_tenders_tab.click()
        print("Clicked on 'New Tenders' tab.")

        all_sub_tab = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//span[normalize-space()='All']"))
        )
        all_sub_tab.click()
        print("Clicked on 'All' sub-tab.")

        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.ID, "awardedDataTable"))
            )
            print("Tender data table (ID: awardedDataTable) loaded on 'All' tab.")
            time.sleep(3)
        except TimeoutException:
            print("Tender table (awardedDataTable) not found on the 'All' tab after waiting.")
            return []

        try:
            # Find the 'Show X entries' dropdown
            show_entries_dropdown = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "awardedDataTable_length"))
            )
            select = Select(show_entries_dropdown)
            
            try:
                select.select_by_value("25")
                print("Selected 25 entries per page.")
            except NoSuchElementException:
                try:
                    select.select_by_value("50")
                    print("Selected 50 entries per page.")
                except NoSuchElementException:
                    print("Could not find '25' or '50' options in the entries dropdown. Proceeding with default.")
            time.sleep(5)
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#awardedDataTable tbody tr:nth-child(20)"))
            )
            print("Table reloaded with new entry count, 20th row is present.")

        except TimeoutException:
            print("No 'Show X entries' dropdown found or it took too long.")
        except Exception as e:
            print(f"Error interacting with 'Show X entries' dropdown: {e}")

        
        table_element = driver.find_element(By.ID, "awardedDataTable")
        table_html = table_element.get_attribute('outerHTML')

        soup = BeautifulSoup(table_html, 'html.parser')
        table = soup.find('table', id="awardedDataTable")

        if not table:
            print("BeautifulSoup could not find the table with ID 'awardedDataTable'.")
            return []

        headers = []
        thead = table.find('thead')
        if thead:
            for th in thead.find_all('th'):
                headers.append(th.text.strip())

        header_to_index_map = {}
        if headers:
            cleaned_headers = [h.replace('\n', ' ').strip() for h in headers]
            for idx, h in enumerate(cleaned_headers):
                header_to_index_map[h] = idx
        else:
            
            header_to_index_map = {
                "NIT/RFP NO": 1,
                "Name of Work / Subwork / Packages": 2,
                "Estimated Cost": 3,
                "Bid Submission Closing Date & Time": 4,
                "EMD Amount": 5,
                "Bid Opening Date & Time": 6
            }

        required_header_names_in_order = list(CSV_COLS_MAP.keys()) 

        tbody = table.find('tbody')
        if tbody:
            for i, tr in enumerate(tbody.find_all('tr')):
                if len(tender_data_raw) >= REQUIRED_TENDER_COUNT:
                    break

                cells = tr.find_all('td')
                if not cells:
                    continue

                tender_record = {}
                valid_record = True
                for required_header in required_header_names_in_order:
                    idx = header_to_index_map.get(required_header)

                    if idx is not None and idx < len(cells):
                        tender_record[required_header] = cells[idx].text.strip()
                    else:
                        print(f"Warning: Missing data for '{required_header}' in row {i+1}. Skipping row.")
                        valid_record = False
                        break

                if valid_record:
                    tender_data_raw.append(tender_record)
                    print(f"Extracted raw record {len(tender_data_raw)}: {tender_record.get('NIT/RFP NO', 'N/A')}")
        else:
            print("Warning: Table body (<tbody>) not found. No data rows to extract.")

    except UnexpectedAlertPresentException as e:
        print("An unexpected alert was detected, possibly due to CPWD Signer.")
        print("Alert message:", e.alert_text)
        raise
    except Exception as e:
        print(f"An error occurred during extraction: {e}")
        if driver:
            # Save screenshot to a location accessible in logs/volumes
            driver.save_screenshot("/opt/airflow/logs/extract_error_screenshot.png")
            print("Screenshot 'extract_error_screenshot.png' saved.")
        raise
    finally:
        if driver:
            driver.quit()

    print(f"Extraction complete. Returning {len(tender_data_raw)} raw records.")
    return tender_data_raw

def transform_tender_data(raw_data: list[dict]) -> str:
    
    if not raw_data:
        print("No raw data received for transformation.")
        return json.dumps([])

    print(f"Received {len(raw_data)} records for transformation.")

    df = pd.DataFrame(raw_data)

    
    for col_name in CSV_COLS_MAP.keys():
        if col_name not in df.columns:
            df[col_name] = None

    
    df_final = df[list(CSV_COLS_MAP.keys())]
    df_final.rename(columns=CSV_COLS_MAP, inplace=True)

    
    df_final = df_final.head(REQUIRED_TENDER_COUNT)

    transformed_data_json = df_final.to_json(orient='records')
    print(f"Transformation complete. Returning {len(df_final)} transformed records (as JSON).")
    return transformed_data_json

def save_tender_data(transformed_data_json: str, output_path: str):
    
    if not transformed_data_json:
        print("No transformed data received for saving.")
        return

    df_transformed = pd.read_json(transformed_data_json, orient='records')

    if df_transformed.empty:
        print("Transformed DataFrame is empty. Nothing to save.")
        return

    df_transformed.to_csv(output_path, index=False)
    print(f"Successfully saved {len(df_transformed)} tenders to {output_path}")