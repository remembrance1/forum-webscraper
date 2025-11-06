# 🕸️ Flask Forum Link Scraper

A lightweight Flask-based web application that allows you to **extract, filter, and export links** from any webpage or online forum — built for speed, usability, and extensibility.

---

## 🚀 Overview

**Flask Forum Link Scraper** helps you quickly find relevant links from a target URL by scanning for keywords in both link text and URLs.  
It also supports an **optional sub-filter**, background task execution, and export options (HTML, CSV, Excel).

This tool was designed with modularity in mind, using **Flask Blueprints** and a structure that’s easy to integrate into a **React frontend** in the future.

---

## ✨ Features

- 🔍 **Keyword Filtering**  
  Extracts all links that contain your chosen keyword in either text or URL.

- 🧩 **Sub-keyword Refinement**  
  Add extra filters to refine results:
  - `,` → OR logic (matches *any* word)  
  - `+` → AND logic (matches *all* words)

  Example:
  ```
  singapore, asean
  ```
  → keeps results containing *either* “singapore” or “asean”.

  ```
  singapore + november
  ```
  → keeps results containing *both* “singapore” and “november”.

- ⚙️ **Asynchronous Scanning**  
  Long-running scans are handled in background threads, allowing responsive navigation.

- 📦 **Export Options**  
  Download results in:
  - `.html` – nicely formatted, browser-viewable
  - `.csv` – for Excel or data tools
  - `.xlsx` – Excel workbook with auto-sizing columns

- 🔐 **User Authentication (optional)**  
  Built-in login and registration using `Flask-Login`, with password hashing and success/error flash messages.

- 🧱 **Blueprint-based Architecture**  
  Modular design makes it easy to extend — new features can be added as separate blueprints.

---

## 🧰 Tech Stack

| Component | Description |
|------------|-------------|
| **Flask** | Web framework |
| **Flask-Login** | Authentication and session management |
| **SQLAlchemy** | ORM for user data |
| **Threading** | Asynchronous scraping |
| **OpenPyXL** | Excel export support |
| **Bootstrap 5** | UI and responsive layout |

---

## 🗂️ Project Structure

```
Scraper2/
│
├── run.py
└── app/
    ├── __init__.py            # Flask app factory
    ├── extensions.py           # db + login_manager initialization
    ├── models/
    │   └── user.py
    ├── blueprints/
    │   ├── main/
    │   │   ├── __init__.py
    │   │   ├── routes.py      # main scraper routes
    │   │   ├── parser.py      # link parsing and subfilter logic
    │   │   ├── fetch.py       # fetch utilities
    │   │   └── tasks.py       # background scan runner
    │   └── auth/
    │       ├── __init__.py
    │       └── routes.py      # registration, login, logout
    ├── static/                 # CSS, JS, favicon
    └── templates/              # HTML templates
```

---

## ⚙️ Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/flask-forum-link-scraper.git
cd flask-forum-link-scraper
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate   # (Linux/macOS)
venv\Scripts\activate      # (Windows)
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the app
```bash
python run.py
```

Then visit:  
👉 `http://127.0.0.1:5000`

---

## 💡 Usage Guide

1. **Enter a Forum URL**  
   Paste the base URL of the site or discussion thread.

2. **Enter a Keyword**  
   The main keyword that must appear in the link or link text.

3. **(Optional) Enter a Sub-keyword**  
   Refine your results using commas (OR) or plus signs (AND).

4. **Click "Scan"**  
   The scraper runs asynchronously and displays progress as results are collected.

5. **Export Results**  
   Choose your preferred export format — HTML, CSV, or Excel.

---

## 🔒 Authentication (optional)

User registration and login functionality are included but optional.  
Passwords are securely hashed, and session management is handled via `Flask-Login`.

---

## 🧱 Future Plans

- ⚡ Integration with a React frontend  
- 🌍 Support for multi-threaded async scraping with `aiohttp`  
- 📊 Interactive charts showing keyword frequency  
- 🔎 Advanced regex-based search filters

---

## 👨‍💻 Author

**Javier Ng**  
Data and Analytics Professional — Ministry of Business, Innovation & Employment (MBIE), New Zealand  
> “Shaping Tomorrow, Today: Innovating with AI and Data at the Core.”

---

## 📝 License

This project is open-source and free to use for educational or personal projects.  
See `LICENSE` for details.
