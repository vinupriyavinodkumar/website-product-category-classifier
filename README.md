# 🛒 Website Product Category Classifier  
Automated website metadata extraction + category prediction using Playwright, GPT-4, and Google Sheets API.

This project visits e-commerce websites, extracts metadata using a headless browser, and classifies what type of products the website sells. It supports both English and non-English websites using a hybrid rule-based + GPT-4 classification system.

---

## 🔍 Features

### Website Metadata Extraction
- Uses **Playwright WebKit** for realistic page rendering  
- Handles pop-ups: cookie banners, sign-up forms, region/language selectors  
- Extracts:
  - `og:title`, `og:description`, keywords  
  - `<meta>` tags  
  - Page title  
  - Headings (H1–H6)  
  - Category-related anchor text  

### Hybrid Category Classification System  
Websites are classified into:

| Code | Category            |
|------|---------------------|
| 9    | Clothing + Shoes    |
| 8    | Clothing            |
| 7    | Shoes               |
| 6    | Lingerie            |
| -    | Unknown / No match  |

- **English pages** → Rule-based keyword classification  
- **Non-English pages** → GPT-4 metadata classification  

### Google Sheets Integration
- Reads URLs from Google Sheets  
- Updates:
  - **Product** column (category code)  
  - **Status** column (1 = success, 0 = failed)  
- Built-in retry logic for API stability  
- Tracks:
  - Timeout errors  
  - SSL errors  
  - GPT errors  
  - Token usage + estimated cost  

---

## 📁 Project Structure
website-product-category-classifier/
│
├── website_classifier.py # Main classifier script
├── README.md # Documentation
├── requirements.txt # Dependencies
├── .gitignore # Ignore secrets and cache files
└── .env.example # Example environment variables

---

## 🧾 Google Sheets Setup

Create a Google Sheet with the following columns:

| Duplicate? | URL | Product | Status | Email | Name | Competitor | Response | Comments |
|------------|-----|---------|--------|-------|------|------------|----------|----------|

**URL** = The website to classify  
**Product** and **Status** = Filled automatically  

### How to get your Spreadsheet ID
Example Sheet URL: https://docs.google.com/spreadsheets/d/1AbCdEfGhIJklMNopQRstuVWxyz12345/edit#gid=0

The **Spreadsheet ID** is the part between `/d/` and `/edit`.

Add it to your `.env` file: GOOGLE_SHEET_ID=your_sheet_id

---

## 🔐 Google API Setup (Service Account)

This project uses a **Google Service Account**.

### Steps:
1. Go to **Google Cloud Console**
2. Enable:
   - Google Sheets API  
   - Google Drive API  
3. Create a **Service Account**
4. Go to **Keys → Add Key → JSON**
5. Download the JSON file locally  
6. Share your Google Sheet with the service account email  
   (example: `example-bot@project-id.iam.gserviceaccount.com`)
7. In `.env`, set: GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service_account.json


---

## 🤖 OpenAI API Setup

Get an API key from:  
https://platform.openai.com/api-keys

Add to `.env`:OPENAI_API_KEY=your_openai_key_here



---

## ⚙️ Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/website-product-category-classifier
cd website-product-category-classifier


### 2. Install Dependencies
pip install -r requirements.txt

### 3. Install playwright browsers
playwright install

### 4. Create .env file

Use .env.example as a template:

OPENAI_API_KEY=your_key
GOOGLE_SHEET_ID=your_sheet_id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json


▶️ Running the Script

python website_classifier.py

The script will:

Read URLs from the Google Sheet
Visit each website
Extract metadata
Classify into category codes
Update the Sheet
Print summary + token usage

------------------------------
📊 Example Console Output

Processing row 5 with URL: https://www.nike.com
Detected language: en
Classified category code: 7
Updated Product column
Updated Status column

----------- Summary ------------
Total URLs processed: 42
Timeout errors: 1
SSL errors: 0
GPT errors: 0
Other errors: 2
Total tokens used: 4152
Estimated cost: $0.19
--------------------------------
