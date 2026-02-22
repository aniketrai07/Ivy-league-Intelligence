# Ivy League Intelligence Web App

An AI-powered real-time Ivy League university data intelligence system built using FastAPI.

This web application automatically scrapes and organizes official data from all 8 Ivy League universities, including:

- Tuition & Fee Structure
- Admissions Requirements
- Application Deadlines
- Academic Programs
- Financial Aid Information
- University Overview

---

## 🚀 Features

- Real-time web scraping
- Change detection (no duplicate storage)
- Per-university scraping mode
- Snapshot + history tracking
- Clean premium UI (Dark Theme)
- FastAPI backend
- SQLite database
- REST API endpoints
- Scheduler support (optional)

---

## 🏫 Ivy League Universities Covered

- Harvard University
- Yale University
- Princeton University
- Columbia University
- Brown University
- Cornell University
- Dartmouth College
- University of Pennsylvania

---

## 🛠 Tech Stack

- FastAPI
- SQLAlchemy
- SQLite
- APScheduler
- Jinja2 Templates
- TailwindCSS
- httpx (async scraping)

---

## ▶️ Run Locally

uvicorn app.main:app --reload

click-  http://127.0.0.1:8000

### 1️⃣ Install dependencies

```bash
pip install -r requirements.txt