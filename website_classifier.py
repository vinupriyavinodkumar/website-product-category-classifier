import time
import os
import asyncio
import openai as OpenApi
import gspread
import ssl
from dotenv import load_dotenv
from google.oauth2 import service_account
from playwright_stealth import stealth_async
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# Load environment variables from the .env file
load_dotenv()

# Read environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is not set in .env")

OpenApi.api_key = OPENAI_API_KEY

# Initialize counters for summary tracking
tokens_used = 0
input_tokens = 0
output_tokens = 0
timeout_errors = 0
ssl_errors = 0
other_errors = 0
metadata_extract_errors = 0
gpt_errors = 0
status = 0

# Record the start time of the script
start_time = time.time()


# Function to authenticate and connect to Google Sheets
def authenticate_google_sheets(credentials_file, spreadsheet_id):
    if not credentials_file:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set in .env")
    if not spreadsheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set in .env")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=scope
    )
    client = gspread.authorize(creds)

    print("Authentication successful!")
    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet


# Function to get the count of valid URLs from the sheet
def get_url_count(sheet):
    # Fetch all records and count how many rows contain a valid URL
    records = sheet.get_all_records(
        expected_headers=[
            "Duplicate",
            "URL",
            "Product",
            "Status",
            "Email",
            "Name",
            "Competitor",
            "Response",
            "Comments",
        ]
    )
    valid_url_count = 0
    for record in records:
        url = record.get("URL")
        if url:  # Check if URL is not empty
            valid_url_count += 1
    return valid_url_count


# Function to handle pop-ups using Playwright
async def handle_popups(page):
    try:
        # Try to find and click the "Accept" button for cookie consent
        accept_button = await page.query_selector('button:has-text("Accept")')
        if accept_button:
            await accept_button.click()
            print("Cookie consent accepted.")
        else:
            print("No cookie consent pop-up found.")
    except Exception as e:
        print("Error while handling cookie consent pop-up:", e)

    try:
        # Try to find and click the "Close" button for modals
        close_button = await page.query_selector_all(
            'button:has-text("Close"), button:has-text("X"), button:has-text("✕"), button[aria-label="Close"]'
        )
        if close_button:
            await close_button.click()
            print("Modal closed.")
        else:
            print("No modal found.")
    except Exception as e:
        print("Error while handling modal:", e)

    try:
        # Detect and handle sign-up/login pop-ups
        signup_modal = await page.query_selector(
            'div:has-text("Sign Up"), div:has-text("Login")'
        )
        if signup_modal:
            close_button = await signup_modal.query_selector(
                'button:has-text("Close"), button:has-text("✖")'
            )
            if close_button:
                await close_button.click()
                print("Sign-up/Login pop-up closed.")
            else:
                await page.keyboard.press("Escape")
                print("Pressed Escape to close the pop-up.")

    except Exception as e:
        print("Error while handling sign-up/login pop-up:", e)

    try:
        # Handle country or language selection pop-up
        language_popup = await page.query_selector(
            'div:has-text("Select Country"), div:has-text("Choose Country"), div:has-text("Select Region"), '
            'div:has-text("Choose Language"), div:has-text("Select Your Location"), div:has-text("Country/Region")'
        )

        if language_popup:
            print("Language/Country selection pop-up detected.")

            # Look for dropdown or button options for English and United Kingdom
            english_option = await page.query_selector(
                'option:has-text("English"), button:has-text("English"), label:has-text("English")'
            )
            uk_option = await page.query_selector(
                'option:has-text("United Kingdom"), button:has-text("United Kingdom"), label:has-text("United Kingdom")'
            )

            # Select English
            if english_option:
                await english_option.click()
                print("Selected English.")

            # Select United Kingdom
            if uk_option:
                await uk_option.click()
                print("Selected United Kingdom.")

            # Look for a "Continue" or "Confirm" button
            confirm_button = await page.query_selector(
                'button:has-text("Continue"), button:has-text("Confirm"), button:has-text("OK"), button:has-text("Save")'
            )
            if confirm_button:
                await confirm_button.click()
                print("Confirmed language/country selection.")

    except Exception as e:
        print("Error while handling language/country selection pop-up:", e)


# Function to handle retries while loading the URL
async def navigate_with_retry(page, url, retries=3, delay=5):
    attempt = 0
    while attempt < retries:
        try:
            print(f"Attempting to navigate to {url} (Attempt {attempt + 1}/{retries})")
            await page.goto(url, timeout=60000)  # Set a longer timeout for loading
            return True  # Successfully navigated
        except PlaywrightTimeoutError:
            print(f"Timeout error occurred while trying to load {url}. Retrying...")
        except Exception as e:
            print(f"Error while trying to load {url}: {e}. Retrying...")

        # Increment attempt counter and wait before retrying
        attempt += 1
        await asyncio.sleep(delay)

    # If all retries failed, return False
    print(f"Failed to navigate to {url} after {retries} attempts.")
    return False


# Retry logic for updating Google Sheets
def update_cell_with_retry(sheet, row, col, value, retries=3, delay=3):
    attempt = 0
    while attempt < retries:
        try:
            sheet.update_cell(row, col, value)
            print(f"Successfully updated row {row}, column {col} with value {value}.")
            return True
        except gspread.exceptions.GSpreadException as e:
            attempt += 1
            print(
                f"Error updating row {row}, column {col}: {e}. Attempt {attempt}/{retries}"
            )
            if attempt < retries:
                time.sleep(delay)
            else:
                print(f"Failed to update after {retries} attempts.")
                return False


# Function to categorize website based on metadata
async def product_categorisation(metadata):
    # Define category keywords for classification
    clothing_keywords = [
        "clothing",
        "clothes",
        "clothings",
        "apparel",
        "appaerls",
        "dress",
        "dresses",
        "tops",
        "top",
        "pants",
        "pant",
        "trousers",
        "trouser",
        "jeans",
        "jean",
        "shorts",
        "short",
        "skirts",
        "skirt",
        "shirts",
        "shirt",
        "jackets",
        "jacket",
        "blouse",
        "blouses",
        "coats",
        "coat",
        "suits",
        "suit",
    ]
    shoes_keywords = [
        "shoes",
        "shoe",
        "footwears",
        "footwear",
        "boots",
        "boot",
        "trainers",
        "trainer",
        "sneakers",
        "sneaker",
        "sandals",
        "sandal",
        "heels",
        "flats",
    ]
    lingerie_keywords = [
        "bras",
        "bra",
        "lingerie",
        "lingeries",
        "lingerie sets",
        "lingerie set",
        "underwear",
        "underwears",
        "undergarments",
        "undergarment",
        "boxers",
        "boxer",
        "briefs",
        "brief",
        "panties",
        "panty",
    ]

    # Convert metadata to lowercase for easier matching
    metadata_lower = metadata.lower()

    # Check if metadata matches any clothing keywords
    if any(keyword in metadata_lower for keyword in clothing_keywords):
        if any(keyword in metadata_lower for keyword in shoes_keywords):
            return "9"  # Clothing + Shoes category
        else:
            return "8"  # Clothing category

    # Check if metadata matches any shoes keywords
    if any(keyword in metadata_lower for keyword in shoes_keywords):
        return "7"  # Shoes category

    # Check if metadata matches any lingerie keywords
    if any(keyword in metadata_lower for keyword in lingerie_keywords):
        return "6"  # Lingerie category

    # If no match found, return '-'
    return "-"


async def metadata_extract(page):
    global metadata_extract_errors

    try:
        # Wait for the page to load completely
        await page.wait_for_load_state("networkidle")

        og_title, page_title, og_description, og_keywords = None, None, None, None
        meta_description, meta_keywords = None, None

        # Try to extract og:title
        try:
            og_title = await page.get_attribute('meta[property="og:title"]', "content")
        except Exception:
            pass

        # Try to extract title
        try:
            page_title = (
                await page.inner_text("title")
                if await page.query_selector("title")
                else "Untitled Page"
            )
        except Exception:
            pass

        # Try to extract og:description
        try:
            og_description = await page.get_attribute(
                'meta[property="og:description"]', "content"
            )
        except Exception:
            pass

        # Try to extract og:keywords
        try:
            og_keywords = await page.get_attribute(
                'meta[property="og:keywords"]', "content"
            )
        except Exception:
            pass

        # Try to extract meta[name="description"]
        try:
            meta_description = await page.get_attribute(
                'meta[name="description"]', "content"
            )
        except Exception:
            pass

        # Try to extract meta[name="keywords"]
        try:
            meta_keywords = await page.get_attribute(
                'meta[name="keywords"]', "content"
            )
        except Exception:
            pass

        metadata_parts = [
            og_title or "",
            og_description or "",
            og_keywords or "",
            meta_description or "",
            meta_keywords or "",
            page_title or "",
        ]
        metadata = " ".join(metadata_parts).strip()

        # Extract headers (h1, h2, h3, h4, h5, h6) and any other relevant content
        headers = await page.query_selector_all("h1, h2, h3, h4, h5, h6")
        header_texts = [await header.inner_text() for header in headers]

        if not header_texts:
            print("No headers found on the page.")

        # Get other metadata like titles, categories, and classes
        category_links = await page.query_selector_all(
            'a[href*="clothing"], a[href*="shoes"], a[href*="lingerie"]'
        )
        category_texts = [await link.inner_text() for link in category_links]

        # Extract the lang attribute from the <html> tag
        html_element = await page.query_selector("html")
        lang = (
            await html_element.get_attribute("lang") or "en"
        )  # Get the lang attribute from <html> tag

        # Combine all extracted metadata into a single string 
        metadata += " " + " ".join(header_texts) + " " + " ".join(category_texts)

        # Include the lang tag in the metadata
        metadata += f" Language: {lang}"

        # Limit to first 500 words
        metadata = " ".join(metadata.split()[:500])

        return lang, metadata
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        metadata_extract_errors += 1
        return None, None


# Function to handle the page language and classification process
async def classify_page(url):

    global timeout_errors, ssl_errors, other_errors

    if not url:
        print("Received empty URL", url)
        return "-", 0

    # Ensure URL starts with "http://" or "https://"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url  # Assume "https://" if missing

    try:
        async with async_playwright() as p:
            browser = await p.webkit.launch(headless=True)
            page = await browser.new_page()
            
            # Block unnecessary resources to speed up loading
            await page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ["image", "font", "media"]
                else route.continue_(),
            )

            try:
                await page.goto(url, wait_until='load', timeout=30000)
            except PlaywrightTimeoutError:
                print(f"Timeout error occurred for URL: {url}")
                timeout_errors += 1
                return "-", 0
            except ssl.SSLError:
                print(f"SSL error occurred for URL: {url}")
                ssl_errors += 1
                return "-", 0

            # Step 2: Extract metadata and language tag from the page
            lang, metadata = await metadata_extract(page)
            print(f"Detected language: {lang}")

            if lang and lang.lower() in {"en", "gb", "us", "en-gb", "en-us"}:
                print(
                    "Page is in English (or a variant: GB or US). Proceeding with rule-based categorization."
                )
                category_code = await product_categorisation(metadata)
                print(f"Classified category code: {category_code}")
                status = 1
                return category_code, status

            else:
                print(
                    "Page is not in English, proceeding with ChatGPT categorization."
                )
                chatgpt_category_code, status = await chatgpt_categorisation(metadata)
                print(f"ChatGPT classified category code: {chatgpt_category_code}")
                return chatgpt_category_code, status

    except Exception as e:
        print(f"Error during page classification: {e}")
        if (
            "SSL peer certificate or SSH remote key was not OK" in str(e)
            or "SSL connect error" in str(e)
        ):
            ssl_errors += 1
        elif "TimeoutError" in str(e):
            timeout_errors += 1
        else:
            other_errors += 1
        category_code = "-"
        status = 0
        return category_code, status


# Function to classify product category using ChatGPT based on metadata
async def chatgpt_categorisation(metadata):
    global tokens_used, input_tokens, output_tokens, gpt_errors
    try:
        # Define the system prompt with instructions for the classification task
        system_prompt = """
        You are a website product categorization assistant. You will be provided the content of a website and tasked with classifying whether the brand or content mentions selling one of the following categories:

        Categories: 
        9: Clothing + Shoes
        8: Clothing
        7: Shoes
        6: Lingerie

        Please classify the website into one of the following categories:
        - 9 for Clothing + Shoes
        - 8 for Clothing
        - 7 for Shoes
        - 6 for Lingerie
        - If none of the categories match, return '-'.

        Return only the corresponding category code (9, 8, 7, 6, or -).
        """

        # Define the user prompt with the metadata extracted from the webpage
        user_prompt = f"""
        Given the following metadata extracted from a webpage, classify the website category:

        Webpage metadata: {metadata}
        """

        # Call OpenAI API to get the category classification
        response = OpenApi.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            max_tokens=50,
            temperature=0.0,
        )

        # Extract the input and output tokens
        input_tokens += response.usage.prompt_tokens
        output_tokens += response.usage.completion_tokens
        tokens_used += response.usage.total_tokens

        # Extract the category number from the response
        category = response.choices[0].message.content.strip()
        status = 1

        # Return the classified category (if valid, otherwise '-')
        if category not in ["9", "8", "7", "6", "-"]:
            print("Received an invalid category response from ChatGPT.")
            category = "-"

        return category, status

    except Exception as e:
        print(f"Error during ChatGPT categorization: {e}")
        gpt_errors += 1
        return "-", 0  # Return '-' in case of error


# Update the product column based on URL content
async def update_product_column(spreadsheet):
    sheet = spreadsheet.get_worksheet(0)
    print("Fetching records from the Google Sheet...")

    # Get the count of valid URLs
    valid_url_count = get_url_count(sheet)
    print(f"Total valid URLs found: {valid_url_count}")

    records = sheet.get_all_records(
        expected_headers=[
            "Duplicate",
            "URL",
            "Product",
            "Status",
            "Email",
            "Name",
            "Competitor",
            "Response",
            "Comments",
        ]
    )

    url_processed = 0

    for idx, record in enumerate(records, start=2):  # Starting from row 2
        url = record.get("URL")

        if not url:  # Skip rows with empty URL
            print(f"Skipping row {idx} due to empty URL.")
            continue

        # Stop processing once the number of URLs processed exceeds valid_url_count
        if url_processed >= valid_url_count:
            print(
                "Reached the limit of valid URLs to process. Stopping further updates."
            )
            break

        # Process the valid URL
        print(f"Processing row {idx} with URL: {url}")
        product_code, status = await classify_page(url)

        # Update the 'Product' column (column 3) with retry logic
        if not update_cell_with_retry(sheet, idx, 3, product_code):
            print(f"Failed to update row {idx} after multiple attempts.")
            continue
        url_processed += 1

        # Update the 'Status' column (column 4) with retry logic
        if not update_cell_with_retry(sheet, idx, 4, status):
            print(f"Failed to update status for row {idx} after multiple attempts.")
            continue

    print("Product column update process completed.")
    # Print summary of key metrics
    print("\n----------- Summary of key Metrics------------")
    print(f"Total URLs processed: {url_processed}")
    print(f"Total valid URLs found: {valid_url_count}")
    print("--------------------------------------------")
    print(f"Total URLs failed due to timeout errors: {timeout_errors}")
    print(f"Total URLs failed due to SSL errors: {ssl_errors}")
    print(f"Total URLs failed during metadata extraction: {metadata_extract_errors}")
    print(f"Total URLs failed during ChatGPT categorization: {gpt_errors}")
    print(f"Total URLs failed due to other errors: {other_errors}")
    print("------------------------------------")
    total_failures = (
        timeout_errors
        + ssl_errors
        + metadata_extract_errors
        + gpt_errors
        + other_errors
    )
    print(f"Total URLs failed: {total_failures} out of {valid_url_count}")
    print(
        f"Total URLs successfully updated: {valid_url_count - total_failures} out of {valid_url_count}"
    )
    print("------------------------------------")
    print(f"Time taken: {time.time() - start_time:.2f} seconds")
    print(f"Total tokens used: {tokens_used}")
    cost = (input_tokens * 0.00003) + (output_tokens * 0.00006)
    print(f"Cost of tokens used: ${cost:.2f}")
    print("---------------Process completed-----------********")
    print("---------------------------------------------------")


if __name__ == "__main__":
    spreadsheet = authenticate_google_sheets(
        GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_SHEET_ID
    )
    asyncio.run(update_product_column(spreadsheet))
