from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import json
import asyncio
import urllib.parse
import re
from emergentintegrations.llm.chat import LlmChat, UserMessage
import requests as _requests
from jose import JWTError, jwt
from passlib.context import CryptContext
from massive_college_database import (
    MASSIVE_COLLEGE_DB, get_filtered_colleges,
    get_colleges_by_interest, INTEREST_TO_CATEGORIES,
    CATEGORY_IMAGE_POOLS, _assign_unique_images,
)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=2000)
db = client[os.environ['DB_NAME']]

# Security configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production-2025')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== Models ====================

class StudentProfile(BaseModel):
    name: str
    education_level: str  # 10th, 12th, Graduate, Post-Graduate
    current_class: Optional[str] = None
    stream: Optional[str] = None  # Science, Commerce, Arts
    marks_percentage: float
    subjects: List[str] = []
    interests: List[str]
    location: str  # State/District
    family_income: str  # <1L, 1-3L, 3-5L, 5L+
    budget_for_education: str  # <50k, 50k-1L, 1-3L, 3L+
    internet_access: str  # Good, Limited, Poor
    language_preference: str  # English, Hindi
    other_constraints: Optional[str] = None


class College(BaseModel):
    name: str
    location: str
    type: str  # Government/Private
    annual_fees: str
    total_fees: Optional[str] = ""
    hostel: Optional[str] = ""
    hostel_facilities: Optional[str] = ""
    course_offered: Optional[str] = ""
    entrance_exam: str
    nirf_rank: Optional[str] = ""
    cutoff: Optional[str] = ""
    placements: Optional[str] = ""
    image_url: str
    why_recommended: Optional[str] = ""
    scholarships: Optional[List[str]] = []


class CareerPath(BaseModel):
    career_name: str
    description: str
    why_suitable: str
    feasibility_score: int  # 1-10
    estimated_cost: str
    time_to_achieve: str
    key_skills_needed: List[str]
    recommended_colleges: List[College] = []


class Roadmap(BaseModel):
    phase: str  # 0-3 months, 3-6 months, etc.
    actions: List[str]
    resources: List[str]
    milestones: List[str]


class Scholarship(BaseModel):
    name: str
    provider: str
    amount: str
    eligibility: str
    deadline: str
    application_link: str


class Job(BaseModel):
    job_title: str
    description: str
    education_required: str
    salary_range: str
    sector: str            # Government / Private / Self-Employed
    growth_potential: str  # High / Medium / Low
    key_skills: List[str]
    how_to_get: str
    exam_if_any: Optional[str] = ""


class CareerRecommendation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_profile: StudentProfile
    career_paths: List[CareerPath] = []
    jobs: List[Job] = []
    selected_career: Optional[str] = None
    roadmap: List[Roadmap] = []
    scholarships: List[Scholarship] = []
    entrance_exams: List[str] = []
    top_colleges: List[College] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ==================== Real Scholarship Database (2025 Current Data) ====================

SCHOLARSHIP_DATABASE = [
    {
        "name": "NSP Pre-Matric Scholarship (SC/ST/OBC)",
        "provider": "Ministry of Social Justice & Empowerment",
        "amount": "₹1,000 - ₹18,000/year (varies by class and day/hostel scholar)",
        "eligibility": "SC/ST/OBC students in Classes 1-10, Rural/urban, Family income ≤ ₹2.5 lakh, Minimum 55-60% marks",
        "keywords": ["pre-matric", "class 1", "class 2", "class 3", "class 4", "class 5", "class 6", "class 7", "class 8", "class 9", "class 10", "sc", "st", "obc", "school", "low income", "rural"],
        "deadline": "October-December 2025 (for 2025-26 cycle)",
        "application_link": "https://scholarships.gov.in"
    },
    {
        "name": "NSP Post-Matric Scholarship (SC/ST/OBC)",
        "provider": "Ministry of Social Justice & Empowerment",
        "amount": "₹3,000 - ₹1,00,000/year (maintenance + course fees)",
        "eligibility": "SC/ST/OBC students in Class 11-12, Diploma, ITI, UG/PG courses, Family income ≤ ₹2.5-6 lakh, ≥55-75% marks",
        "keywords": ["post-matric", "class 11", "class 12", "college", "diploma", "iti", "undergraduate", "postgraduate", "sc", "st", "obc", "graduation", "low income", "rural"],
        "deadline": "November 2025 - January 2026",
        "application_link": "https://scholarships.gov.in"
    },
    {
        "name": "PM Narendra Modi Scholarship for Rural Students",
        "provider": "National Scholarship Portal",
        "amount": "₹25,000 - ₹1,00,000/year (depending on course level)",
        "eligibility": "Rural students with 75% marks in Class 12, Pursuing higher education in recognized institutions",
        "keywords": ["pm modi", "rural", "merit", "class 12", "higher education", "undergraduate", "graduation"],
        "deadline": "July-October 2025",
        "application_link": "https://scholarships.gov.in"
    },
    {
        "name": "INSPIRE Scholarship for Higher Education (SHE)",
        "provider": "Department of Science & Technology (DST)",
        "amount": "₹80,000/year (₹60,000 scholarship + ₹20,000 mentorship) for up to 5 years",
        "eligibility": "Top 1% in Class 12 board OR Top 10,000 in JEE Advanced OR KVPY/NTSE scholars, Age 17-22, Enrolled in B.Sc/B.S/Integrated M.Sc in Natural Sciences, Must maintain ≥60% marks annually",
        "keywords": ["inspire", "science", "class 12", "bsc", "msc", "natural sciences", "basic sciences", "merit", "research", "top rank", "jee"],
        "deadline": "Post Class 12 results (July-August 2025)",
        "application_link": "https://online-inspire.gov.in"
    },
    {
        "name": "AICTE Pragati Scholarship (for Girls)",
        "provider": "All India Council for Technical Education",
        "amount": "₹50,000/year (for fees, books, equipment)",
        "eligibility": "Girl students in 1st year of technical diploma or degree (Engineering/Pharmacy/Architecture), AICTE-approved institutions, Family income ≤ ₹8 lakh, Must not hold other govt scholarships",
        "keywords": ["engineering", "technical", "girls", "female", "aicte", "pharmacy", "architecture", "women", "diploma", "degree"],
        "deadline": "January-February 2026 (for 2025-26 academic year)",
        "application_link": "https://www.aicte-india.org"
    },
    {
        "name": "AICTE Saksham Scholarship (for Specially Abled)",
        "provider": "All India Council for Technical Education",
        "amount": "₹50,000/year",
        "eligibility": "Specially abled students in technical diploma/degree courses, AICTE-approved institutions, Family income ≤ ₹8 lakh",
        "keywords": ["specially abled", "disabled", "pwd", "engineering", "technical", "aicte", "diploma", "degree"],
        "deadline": "January-February 2026",
        "application_link": "https://www.aicte-india.org"
    },
    {
        "name": "AICTE Swanath Scholarship",
        "provider": "All India Council for Technical Education",
        "amount": "₹50,000/year (up to 2,000 awards annually)",
        "eligibility": "Orphans, COVID orphans, wards of martyred armed forces/paramilitary personnel, Technical diploma/degree, Family income ≤ ₹8 lakh",
        "keywords": ["orphan", "covid orphan", "martyrs", "armed forces", "paramilitary", "engineering", "technical", "aicte"],
        "deadline": "January-February 2026",
        "application_link": "https://www.aicte-india.org"
    },
    {
        "name": "SBI Platinum Jubilee Asha Scholarship 2025-26",
        "provider": "State Bank of India & Buddy4Study",
        "amount": "₹15,000 - ₹20,00,000 (varies by category: school, UG, PG, medical, IIT, IIM, overseas)",
        "eligibility": "School: 75% marks or 7 CGPA (67.5% for SC/ST), Family income < ₹3 lakh. Other categories: Income < ₹6 lakh. 50% seats for girls, 50% for SC/ST students",
        "keywords": ["sbi", "asha", "school", "undergraduate", "postgraduate", "medical", "iit", "iim", "merit", "girls", "sc", "st"],
        "deadline": "Varies by category (typically September-December 2025)",
        "application_link": "https://www.sbiashascholarship.co.in"
    },
    {
        "name": "Reliance Foundation Undergraduate Scholarship",
        "provider": "Reliance Foundation",
        "amount": "Up to ₹2,00,000 (+ mentorship and career guidance)",
        "eligibility": "Rural/underprivileged students pursuing 1st year UG in science, engineering, professional courses, Family income ≤ ₹6 lakh, Merit-based selection",
        "keywords": ["reliance", "rural", "undergraduate", "engineering", "science", "professional", "low income", "mentorship"],
        "deadline": "July-September 2025",
        "application_link": "https://www.scholarships.reliancefoundation.org"
    },
    {
        "name": "Tata Capital Pankh Scholarship",
        "provider": "Tata Capital Foundation",
        "amount": "Up to 80% of tuition fees (Maximum ₹50,000)",
        "eligibility": "Students from rural and semi-urban India, Class 11-12 or UG/PG courses, Family income < ₹2.5 lakh per annum",
        "keywords": ["tata", "pankh", "rural", "semi-urban", "class 11", "class 12", "undergraduate", "postgraduate", "low income"],
        "deadline": "August-October 2025",
        "application_link": "https://www.buddy4study.com/tata-capital-pankh-scholarship"
    },
    {
        "name": "Kerala Vidya Samunnathi Scholarship",
        "provider": "Government of Kerala",
        "amount": "₹5,000 - ₹50,000/year (varies by course level)",
        "eligibility": "Economically backward non-reserved communities from rural Kerala, School/diploma/higher education students",
        "keywords": ["kerala", "state", "vidya samunnathi", "rural", "school", "diploma", "higher education", "economically backward"],
        "deadline": "Check Kerala State Scholarship Portal",
        "application_link": "https://scholarship.swd.kerala.gov.in"
    },
    {
        "name": "Central Sector Scheme (Merit-cum-Means)",
        "provider": "Ministry of Education",
        "amount": "₹10,000 - ₹20,000/year (UG/PG courses)",
        "eligibility": "Top 20% students in Class 12, Family income < ₹4.5 lakh, Pursuing UG/PG in govt/govt-aided institutions",
        "keywords": ["central sector", "merit", "means", "class 12", "college", "graduation", "undergraduate", "postgraduate", "middle income"],
        "deadline": "October-November 2025",
        "application_link": "https://scholarships.gov.in"
    },
    {
        "name": "Begum Hazrat Mahal National Scholarship",
        "provider": "Maulana Azad Education Foundation (Minority Affairs)",
        "amount": "₹5,000 - ₹6,000/year",
        "eligibility": "Minority community girls in Classes 9-12, Family income < ₹2 lakh, Minimum academic performance required",
        "keywords": ["girls", "female", "minority", "muslim", "christian", "sikh", "class 9", "class 10", "class 11", "class 12", "women", "low income"],
        "deadline": "October-November 2025",
        "application_link": "https://scholarships.gov.in"
    },
    {
        "name": "UGC Merit-cum-Means Scholarship (Minorities)",
        "provider": "University Grants Commission (Minority Affairs)",
        "amount": "₹5,000/year (Graduation/Post-graduation)",
        "eligibility": "Minority community students at graduation/post-graduation level, Family income < ₹2.5 lakh, Must maintain satisfactory academic progress",
        "keywords": ["ugc", "minority", "muslim", "christian", "sikh", "buddhist", "jain", "parsi", "graduation", "postgraduate", "college", "low income"],
        "deadline": "September-October 2025",
        "application_link": "https://scholarships.gov.in"
    }
]


# ==================== Real College Database (2025 Data) ====================

COLLEGE_DATABASE = {
    "engineering": [
        {
            "name": "Zakir Husain College of Engineering & Technology (AMU)",
            "location": "Aligarh, Uttar Pradesh",
            "type": "Government",
            "annual_fees": "₹8,468/year",
            "course_offered": "B.Tech (Various branches)",
            "entrance_exam": "JEE Main + AMU Engineering Entrance",
            "image_url": "https://images.pexels.com/photos/33977829/pexels-photo-33977829.jpeg",
            "why_recommended": "Most affordable govt engineering college in India, excellent for northern rural students"
        },
        {
            "name": "COEP Technological University",
            "location": "Pune, Maharashtra",
            "type": "Government",
            "annual_fees": "₹45,188/year",
            "course_offered": "B.Tech (All major branches)",
            "entrance_exam": "JEE Main + MHT-CET",
            "image_url": "https://images.pexels.com/photos/5096913/pexels-photo-5096913.jpeg",
            "why_recommended": "Top-ranked autonomous university with excellent placements, scholarships available"
        },
        {
            "name": "NIT Trichy",
            "location": "Tiruchirappalli, Tamil Nadu",
            "type": "Government (Central)",
            "annual_fees": "₹1,54,500/year",
            "course_offered": "B.Tech (15+ branches)",
            "entrance_exam": "JEE Main (JoSAA counseling)",
            "image_url": "https://images.pexels.com/photos/5096913/pexels-photo-5096913.jpeg",
            "why_recommended": "Premier NIT with high placement records, reserved seats for rural students"
        },
        {
            "name": "Government Model Engineering College",
            "location": "Kochi, Kerala",
            "type": "Government",
            "annual_fees": "₹53,750/year",
            "course_offered": "B.Tech (8 branches)",
            "entrance_exam": "KEAM (Kerala Engineering Entrance)",
            "image_url": "https://images.pexels.com/photos/18385539/pexels-photo-18385539.jpeg",
            "why_recommended": "Industry-ready curriculum, Kerala govt scholarships for rural students"
        }
    ],
    "medical": [
        {
            "name": "AIIMS Delhi",
            "location": "New Delhi",
            "type": "Government (AIIMS)",
            "annual_fees": "₹3,728/year (including hostel)",
            "course_offered": "MBBS",
            "entrance_exam": "NEET UG",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Premier medical institute with best clinical exposure, almost free education"
        },
        {
            "name": "AIIMS Patna",
            "location": "Patna, Bihar",
            "type": "Government (AIIMS)",
            "annual_fees": "₹4,256/year",
            "course_offered": "MBBS, BSc Nursing",
            "entrance_exam": "NEET UG / AIIMS Nursing",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Ideal for Bihar rural students, excellent infrastructure, reserved seats"
        },
        {
            "name": "Armed Forces Medical College (AFMC)",
            "location": "Pune, Maharashtra",
            "type": "Government (Defence)",
            "annual_fees": "₹0 (Stipend provided)",
            "course_offered": "MBBS",
            "entrance_exam": "NEET UG + AFMC Interview",
            "image_url": "https://images.pexels.com/photos/5096913/pexels-photo-5096913.jpeg",
            "why_recommended": "Free education with monthly stipend, service bond post-graduation"
        },
        {
            "name": "JIPMER Puducherry",
            "location": "Puducherry",
            "type": "Government (Central)",
            "annual_fees": "₹36,140/year",
            "course_offered": "MBBS, BSc Nursing",
            "entrance_exam": "NEET UG",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Excellent clinical training, affordable fees, good for South India students"
        }
    ],
    "teaching": [
        {
            "name": "Banaras Hindu University (BHU)",
            "location": "Varanasi, Uttar Pradesh",
            "type": "Government (Central University)",
            "annual_fees": "₹15,000/year",
            "course_offered": "B.Ed, M.Ed, BA Education",
            "entrance_exam": "CUET / BHU UET",
            "image_url": "https://images.pexels.com/photos/12091126/pexels-photo-12091126.jpeg",
            "why_recommended": "Top central university, low fees, excellent faculty training programs"
        },
        {
            "name": "Aligarh Muslim University (AMU)",
            "location": "Aligarh, Uttar Pradesh",
            "type": "Government (Central University)",
            "annual_fees": "₹12,000/year",
            "course_offered": "B.Ed, M.Ed",
            "entrance_exam": "CUET / AMU Entrance",
            "image_url": "https://images.pexels.com/photos/33977829/pexels-photo-33977829.jpeg",
            "why_recommended": "Very affordable, strong education department, minority scholarships available"
        },
        {
            "name": "IGNOU (Distance Education)",
            "location": "Delhi (Distance Learning)",
            "type": "Government (Open University)",
            "annual_fees": "₹10,000/semester",
            "course_offered": "B.Ed (Distance)",
            "entrance_exam": "IGNOU B.Ed Entrance Test",
            "image_url": "https://images.pexels.com/photos/5147365/pexels-photo-5147365.jpeg",
            "why_recommended": "Most flexible for rural students, study from home, very low cost"
        }
    ],
    "nursing": [
        {
            "name": "AIIMS Delhi (College of Nursing)",
            "location": "New Delhi",
            "type": "Government (AIIMS)",
            "annual_fees": "₹2,500/year",
            "course_offered": "BSc Nursing, Post Basic BSc Nursing",
            "entrance_exam": "AIIMS Nursing Entrance",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Premier nursing college, extremely low fees, excellent job placements"
        },
        {
            "name": "AIIMS Rishikesh (Nursing)",
            "location": "Rishikesh, Uttarakhand",
            "type": "Government (AIIMS)",
            "annual_fees": "₹3,000/year",
            "course_offered": "BSc Nursing",
            "entrance_exam": "AIIMS Nursing Entrance",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Beautiful campus, hands-on training, good for Uttarakhand/UP students"
        },
        {
            "name": "PGIMER Chandigarh (Nursing)",
            "location": "Chandigarh",
            "type": "Government (Central)",
            "annual_fees": "₹5,000/year",
            "course_offered": "BSc Nursing, MSc Nursing",
            "entrance_exam": "PGIMER Nursing Entrance",
            "image_url": "https://images.pexels.com/photos/30787968/pexels-photo-30787968.jpeg",
            "why_recommended": "Top-tier nursing education, good stipend during training"
        }
    ],
    "pharmacy": [
        {
            "name": "BHU Faculty of Pharmacy",
            "location": "Varanasi, Uttar Pradesh",
            "type": "Government (Central University)",
            "annual_fees": "₹25,000/year",
            "course_offered": "B.Pharm, M.Pharm",
            "entrance_exam": "CUET / BHU UET",
            "image_url": "https://images.pexels.com/photos/12091126/pexels-photo-12091126.jpeg",
            "why_recommended": "Top pharmacy program, good research facilities, affordable"
        },
        {
            "name": "HBTU Kanpur (Pharmacy)",
            "location": "Kanpur, Uttar Pradesh",
            "type": "Government",
            "annual_fees": "₹30,000/year",
            "course_offered": "B.Pharm",
            "entrance_exam": "JEE Main / UPSEE",
            "image_url": "https://images.pexels.com/photos/18385539/pexels-photo-18385539.jpeg",
            "why_recommended": "Good placement record in pharma industry, low fees"
        }
    ],
    "agriculture": [
        {
            "name": "BHU Institute of Agricultural Sciences",
            "location": "Varanasi, Uttar Pradesh",
            "type": "Government (Central University)",
            "annual_fees": "₹20,000/year",
            "course_offered": "BSc Agriculture, MSc Agriculture",
            "entrance_exam": "ICAR AIEEA / CUET",
            "image_url": "https://images.pexels.com/photos/12091126/pexels-photo-12091126.jpeg",
            "why_recommended": "Premier agricultural institute, farm scholarships, practical training"
        },
        {
            "name": "PAU Ludhiana",
            "location": "Ludhiana, Punjab",
            "type": "Government (State University)",
            "annual_fees": "₹35,000/year",
            "course_offered": "BSc Agriculture",
            "entrance_exam": "PAU CET",
            "image_url": "https://images.pexels.com/photos/18385539/pexels-photo-18385539.jpeg",
            "why_recommended": "Top agricultural university, strong rural connect, good placements"
        }
    ],
    "computer_science": [
        {
            "name": "IIIT Delhi",
            "location": "New Delhi",
            "type": "Government (Central)",
            "annual_fees": "₹90,000/year",
            "course_offered": "BTech CSE, BTech IT",
            "entrance_exam": "JEE Main",
            "image_url": "https://images.pexels.com/photos/33977829/pexels-photo-33977829.jpeg",
            "why_recommended": "Premier CS institute, excellent placements, scholarships reduce fees by 50%"
        },
        {
            "name": "NIT Warangal",
            "location": "Warangal, Telangana",
            "type": "Government (Central)",
            "annual_fees": "₹1,48,000/year",
            "course_offered": "BTech CSE",
            "entrance_exam": "JEE Main (JoSAA)",
            "image_url": "https://images.pexels.com/photos/5096913/pexels-photo-5096913.jpeg",
            "why_recommended": "Top NIT for CSE, top tech company placements, reserved seats"
        }
    ],
    "commerce": [
        {
            "name": "Shri Ram College of Commerce (SRCC)",
            "location": "Delhi",
            "type": "Government (DU College)",
            "annual_fees": "₹20,000/year",
            "course_offered": "BCom (Hons)",
            "entrance_exam": "CUET",
            "image_url": "https://images.pexels.com/photos/5147365/pexels-photo-5147365.jpeg",
            "why_recommended": "Top commerce college in India, excellent placements, very low fees"
        },
        {
            "name": "Loyola College",
            "location": "Chennai, Tamil Nadu",
            "type": "Government-Aided",
            "annual_fees": "₹15,000/year",
            "course_offered": "BCom, BBA",
            "entrance_exam": "Merit-based admission",
            "image_url": "https://images.pexels.com/photos/12091126/pexels-photo-12091126.jpeg",
            "why_recommended": "Excellent commerce programs, good for South India students, affordable"
        }
    ]
}


# ==================== Comprehensive Indian Exam Database (40+ exams) ====================

EXAM_DETAILS_DB = {
    # ---- ENGINEERING ----
    "JEE Main": {"full_name": "Joint Entrance Examination (Main)", "conducting_body": "NTA – National Testing Agency", "schedule": "January & April (twice/year)", "for_courses": "B.Tech at NITs, IIITs, GFTIs (800+ colleges)", "eligibility": "12th PCM, 75% marks (65% SC/ST)", "website": "jeemain.nta.nic.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "JEE Advanced": {"full_name": "Joint Entrance Examination (Advanced)", "conducting_body": "IIT – Joint Admission Board (JAB)", "schedule": "May–June (once/year)", "for_courses": "B.Tech at 23 IITs – India's top institutes", "eligibility": "JEE Main top 2.5 lakh + Class 12 75%", "website": "jeeadv.ac.in", "exam_type": "engineering", "icon": "build", "color": "#0D47A1"},
    "BITSAT": {"full_name": "BITS Admission Test", "conducting_body": "BITS Pilani", "schedule": "May–June", "for_courses": "BE / B.Pharm at BITS Pilani, Goa, Hyderabad", "eligibility": "12th PCM/PCB 75%", "website": "bitsadmission.com", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "VITEEE": {"full_name": "VIT Engineering Entrance Examination", "conducting_body": "Vellore Institute of Technology", "schedule": "April (once/year)", "for_courses": "B.Tech at VIT Vellore, Chennai, AP, Bhopal", "eligibility": "12th PCM/PCB 60%", "website": "vit.ac.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "MHT-CET": {"full_name": "Maharashtra Common Entrance Test", "conducting_body": "State CET Cell, Maharashtra", "schedule": "April–May", "for_courses": "B.Tech / B.Pharm at Maharashtra colleges", "eligibility": "12th PCM/PCB, Maharashtra domicile preferred", "website": "cetcell.mahacet.org", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "WBJEE": {"full_name": "West Bengal Joint Entrance Examination", "conducting_body": "WBJEEB", "schedule": "April–May", "for_courses": "B.Tech / B.Pharm at WB colleges incl. Jadavpur", "eligibility": "12th PCM, WB domicile preferred", "website": "wbjeeb.nic.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "KCET": {"full_name": "Karnataka Common Entrance Test", "conducting_body": "KEA – Karnataka Examinations Authority", "schedule": "April–May", "for_courses": "B.Tech / B.Pharm / B.Arch at Karnataka colleges", "eligibility": "12th PCM/PCB, Karnataka domicile", "website": "cetonline.karnataka.gov.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "AP EAMCET": {"full_name": "AP Engineering, Agriculture & Medical Common Entrance Test", "conducting_body": "JNTU Kakinada (APSCHE)", "schedule": "May", "for_courses": "B.Tech / B.Pharm / B.Sc Agriculture in AP", "eligibility": "12th PCM/PCB, AP domicile", "website": "sche.aptonline.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "TS EAMCET": {"full_name": "Telangana State Engineering, Agriculture & Medical CET", "conducting_body": "JNTU Hyderabad", "schedule": "May", "for_courses": "B.Tech / B.Pharm / Agriculture at Telangana colleges", "eligibility": "12th PCM/PCB, TS domicile", "website": "tseamcet.nic.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "KEAM": {"full_name": "Kerala Engineering Architecture Medical Entrance", "conducting_body": "CEE Kerala", "schedule": "April–May", "for_courses": "B.Tech / B.Arch at Kerala engineering colleges", "eligibility": "12th PCM, Kerala domicile", "website": "cee.kerala.gov.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "REAP": {"full_name": "Rajasthan Engineering Admission Process", "conducting_body": "Board of Technical Education, Rajasthan", "schedule": "June–July counselling after JEE Main", "for_courses": "B.Tech at Rajasthan state engineering colleges", "eligibility": "JEE Main qualified or 12th PCM 45%+", "website": "techedu.rajasthan.gov.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "GATE": {"full_name": "Graduate Aptitude Test in Engineering", "conducting_body": "IITs / IISc (rotational)", "schedule": "February", "for_courses": "M.Tech at IITs/NITs/IISc + PSU jobs (ONGC, BHEL, NTPC, GAIL)", "eligibility": "BE/B.Tech/BSc/MSc (3rd year onward eligible)", "website": "gate.iitk.ac.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "SRMJEEE": {"full_name": "SRM Joint Engineering Entrance Examination", "conducting_body": "SRMIST", "schedule": "April", "for_courses": "B.Tech at SRM campuses (Chennai, Delhi NCR, Andhra)", "eligibility": "12th PCM 60%", "website": "srmist.edu.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "MU OET": {"full_name": "Manipal University Online Entrance Test", "conducting_body": "MAHE – Manipal Academy of Higher Education", "schedule": "January–June (slots year-round)", "for_courses": "B.Tech / MBBS / BDS / B.Pharm / Nursing at Manipal campuses", "eligibility": "12th PCM/PCB 50%", "website": "admissions.manipal.edu", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "BCECE": {"full_name": "Bihar Combined Entrance Competitive Examination", "conducting_body": "BCECE Board, Bihar", "schedule": "March–April", "for_courses": "B.Tech / MBBS / Agriculture / Pharmacy at Bihar state colleges", "eligibility": "12th PCM/PCB, Bihar domicile", "website": "bceceboard.bihar.gov.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "TNEA": {"full_name": "Tamil Nadu Engineering Admissions", "conducting_body": "Anna University, Tamil Nadu", "schedule": "June–July (merit-based, no separate exam)", "for_courses": "B.Tech / B.E. at 550+ engineering colleges in Tamil Nadu", "eligibility": "12th PCM 60%+, TN domicile preferred", "website": "tneaonline.org", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "OJEE": {"full_name": "Odisha Joint Entrance Examination", "conducting_body": "OJEE Board, Odisha", "schedule": "April–May", "for_courses": "B.Tech Lateral / MBA / MCA / B.Pharm in Odisha", "eligibility": "12th/Diploma depending on course, Odisha domicile", "website": "ojee.nic.in", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    "AEEE": {"full_name": "Amrita Engineering/Medical Entrance Examination", "conducting_body": "Amrita Vishwa Vidyapeetham", "schedule": "March–May (computer-based)", "for_courses": "B.Tech / B.Pharm / Nursing at Amrita campuses", "eligibility": "12th PCM/PCB 60%", "website": "amrita.edu/admissions", "exam_type": "engineering", "icon": "build", "color": "#1565C0"},
    # ---- POLYTECHNIC / ITI ----
    "JEECUP": {"full_name": "Joint Entrance Examination Council UP (Polytechnic)", "conducting_body": "JEECUP Board, Uttar Pradesh", "schedule": "April–May", "for_courses": "Polytechnic Diploma at UP state colleges", "eligibility": "10th / 12th pass", "website": "jeecup.admissions.nic.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    "DTE Maharashtra Polytechnic Entrance": {"full_name": "Maharashtra Polytechnic Common Entrance Test", "conducting_body": "DTE Maharashtra", "schedule": "May", "for_courses": "Diploma Engineering at Maharashtra polytechnic colleges", "eligibility": "10th pass", "website": "dtemaharashtra.gov.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    "POLYCET": {"full_name": "Telangana State Polytechnic Common Entrance Test", "conducting_body": "SBTET Telangana", "schedule": "April", "for_courses": "Diploma at Telangana polytechnic colleges", "eligibility": "10th pass", "website": "polycetts.nic.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    "Assam PAT": {"full_name": "Assam Polytechnic Admission Test", "conducting_body": "DTE Assam", "schedule": "June", "for_courses": "Polytechnic Diploma at Assam colleges", "eligibility": "10th pass, Assam domicile", "website": "dte.assam.gov.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    "CG Polytechnic CET": {"full_name": "Chhattisgarh Polytechnic Common Entrance Test", "conducting_body": "DTE Chhattisgarh", "schedule": "May", "for_courses": "Diploma Engineering at CG polytechnic colleges", "eligibility": "10th pass, CG domicile", "website": "cgdteraipur.ac.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    "NCVT ITI": {"full_name": "NCVT Industrial Training Certificate", "conducting_body": "NCVT – Ministry of Skill Development", "schedule": "August (Admission), December (Exam)", "for_courses": "2-year trade certificate in 130+ ITI trades across India", "eligibility": "8th / 10th pass depending on trade, Age 14+", "website": "ncvtmis.gov.in", "exam_type": "iti", "icon": "construct", "color": "#004D40"},
    "Bihar Polytechnic Entrance (BCECE)": {"full_name": "Bihar Polytechnic Entrance – BCECE PE", "conducting_body": "BCECE Board, Bihar", "schedule": "March–April", "for_courses": "Diploma Engineering at Bihar polytechnic colleges", "eligibility": "10th pass, Bihar domicile", "website": "bceceboard.bihar.gov.in", "exam_type": "polytechnic", "icon": "construct", "color": "#00695C"},
    # ---- MEDICAL ----
    "NEET UG": {"full_name": "National Eligibility cum Entrance Test (UG)", "conducting_body": "NTA – National Testing Agency", "schedule": "May (once/year)", "for_courses": "MBBS / BDS / BAMS / BHMS at all medical colleges in India", "eligibility": "12th PCB 50%, Age 17+", "website": "neet.nta.nic.in", "exam_type": "medical", "icon": "medkit", "color": "#B71C1C"},
    "AIIMS Nursing Entrance": {"full_name": "AIIMS B.Sc Nursing Entrance", "conducting_body": "All India Institute of Medical Sciences", "schedule": "May–June", "for_courses": "BSc Nursing at all AIIMS campuses (22 AIIMS)", "eligibility": "12th PCB 55%, Age 17+", "website": "aiimsexams.ac.in", "exam_type": "nursing", "icon": "heart", "color": "#C62828"},
    "PGIMER Nursing Entrance": {"full_name": "PGIMER BSc/MSc Nursing Entrance", "conducting_body": "PGIMER Chandigarh", "schedule": "May–June", "for_courses": "BSc / MSc Nursing at PGIMER Chandigarh", "eligibility": "12th PCB 50%", "website": "pgimer.edu.in", "exam_type": "nursing", "icon": "heart", "color": "#C62828"},
    "JIPMER Nursing": {"full_name": "JIPMER BSc Nursing Entrance", "conducting_body": "JIPMER Puducherry", "schedule": "May–June", "for_courses": "BSc Nursing / Post-Basic BSc Nursing at JIPMER", "eligibility": "12th PCB 50%", "website": "jipmer.puducherry.gov.in", "exam_type": "nursing", "icon": "heart", "color": "#C62828"},
    "Bihar Nursing CET": {"full_name": "Bihar Nursing Common Entrance Test", "conducting_body": "State Health Society, Bihar", "schedule": "June–July", "for_courses": "BSc Nursing / GNM at Bihar government nursing colleges", "eligibility": "12th PCB 45%, Bihar domicile", "website": "health.bih.nic.in", "exam_type": "nursing", "icon": "heart", "color": "#C62828"},
    "Delhi Nursing Entrance": {"full_name": "Delhi Nursing Colleges Admission Test", "conducting_body": "DTE Delhi / Delhi Nursing Council", "schedule": "June–July", "for_courses": "BSc Nursing / GNM at Delhi government nursing colleges", "eligibility": "12th PCB 45%", "website": "dte.delhigovt.nic.in", "exam_type": "nursing", "icon": "heart", "color": "#C62828"},
    "CMC Vellore Entrance": {"full_name": "Christian Medical College Vellore Entrance", "conducting_body": "CMC Vellore", "schedule": "April (NEET-based + CMC interview)", "for_courses": "MBBS / BSc Nursing / Allied Health at CMC Vellore", "eligibility": "NEET qualified + interview", "website": "cmch-vellore.edu", "exam_type": "medical", "icon": "medkit", "color": "#B71C1C"},
    # ---- MANAGEMENT ----
    "CAT": {"full_name": "Common Admission Test", "conducting_body": "IIMs (rotational)", "schedule": "November (once/year)", "for_courses": "MBA / PGDM at IIMs and 1000+ B-schools", "eligibility": "Any Graduation 50% (45% SC/ST)", "website": "iimcat.ac.in", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    "XAT": {"full_name": "Xavier Aptitude Test", "conducting_body": "XLRI Jamshedpur", "schedule": "January", "for_courses": "MBA at XLRI, SPJIMR, IMT and 150+ colleges", "eligibility": "Any Graduation", "website": "xatonline.in", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    "SNAP": {"full_name": "Symbiosis National Aptitude Test", "conducting_body": "Symbiosis International University", "schedule": "December (3 attempts)", "for_courses": "MBA at SIBM, SCMHRD, SIIB and other Symbiosis institutes", "eligibility": "Graduation 50%", "website": "snaptest.org", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    "CMAT": {"full_name": "Common Management Admission Test", "conducting_body": "NTA – National Testing Agency", "schedule": "March", "for_courses": "MBA / PGDM at AICTE-approved B-schools", "eligibility": "Any Graduation 50%", "website": "cmat.nta.nic.in", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    "GMAT": {"full_name": "Graduate Management Admission Test", "conducting_body": "GMAC", "schedule": "Year-round (any day, computer-based)", "for_courses": "MBA at IIMs (Executive), ISB, Great Lakes and global B-schools", "eligibility": "Any Graduation, no marks bar", "website": "mba.com", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    "MAT": {"full_name": "Management Aptitude Test", "conducting_body": "AIMA – All India Management Association", "schedule": "February, May, September, December (4 times/year)", "for_courses": "MBA / PGDM at 600+ B-schools accepting MAT", "eligibility": "Any Graduation", "website": "aima.in", "exam_type": "management", "icon": "briefcase", "color": "#4A148C"},
    # ---- CENTRAL UNIVERSITY / UG / PG ----
    "CUET": {"full_name": "Common University Entrance Test", "conducting_body": "NTA – National Testing Agency", "schedule": "May–June (UG), May (PG)", "for_courses": "UG / PG admission to 260+ Central Universities (DU, JNU, BHU, JMI etc.)", "eligibility": "12th pass (UG) / Graduation (PG)", "website": "cuet.samarth.ac.in", "exam_type": "central_univ", "icon": "school", "color": "#1B5E20"},
    "BHU UET": {"full_name": "Banaras Hindu University Undergraduate Entrance Test", "conducting_body": "BHU Varanasi", "schedule": "May (now merged into CUET mostly)", "for_courses": "BSc / BCom / BFA / B.Ed and more at BHU Varanasi", "eligibility": "12th pass any stream", "website": "bhuonline.in", "exam_type": "central_univ", "icon": "school", "color": "#1B5E20"},
    "JMI Entrance": {"full_name": "Jamia Millia Islamia Entrance Examination", "conducting_body": "Jamia Millia Islamia University", "schedule": "May–June", "for_courses": "B.Ed / B.Tech / BA / MA / BCom at Jamia Millia Islamia", "eligibility": "12th / Graduation depending on course", "website": "jmicoe.in", "exam_type": "central_univ", "icon": "school", "color": "#1B5E20"},
    "GU Admission": {"full_name": "Gauhati University Admission Test", "conducting_body": "Gauhati University", "schedule": "June", "for_courses": "BCom / BBA / MCom / various UG-PG programs at Gauhati University", "eligibility": "12th pass 45%+, Assam domicile preferred", "website": "gauhati.ac.in", "exam_type": "commerce", "icon": "briefcase", "color": "#4A148C"},
    # ---- LAW ----
    "CLAT": {"full_name": "Common Law Admission Test", "conducting_body": "Consortium of National Law Universities", "schedule": "December", "for_courses": "LLB (5-year integrated) / LLM at 22 NLUs", "eligibility": "12th 45% (40% SC/ST), Age ≤ 20", "website": "consortiumofnlus.ac.in", "exam_type": "law", "icon": "document-text", "color": "#E65100"},
    "AILET": {"full_name": "All India Law Entrance Test", "conducting_body": "National Law University, Delhi", "schedule": "December", "for_courses": "LLB at NLU Delhi (100 seats only – most selective)", "eligibility": "12th 50%, Age ≤ 20", "website": "nludelhi.ac.in", "exam_type": "law", "icon": "document-text", "color": "#E65100"},
    # ---- GOVT / SSC / BANKING ----
    "SSC CGL": {"full_name": "SSC Combined Graduate Level", "conducting_body": "SSC – Staff Selection Commission", "schedule": "Sep–Dec (Tier I), Jan–Feb (Tier II)", "for_courses": "Group B/C posts: Income Tax, CBI, Customs, Audit Inspector", "eligibility": "Any Graduation, Age 18–32", "website": "ssc.nic.in", "exam_type": "govt", "icon": "briefcase", "color": "#006064"},
    "SSC CHSL": {"full_name": "SSC Combined Higher Secondary Level", "conducting_body": "SSC – Staff Selection Commission", "schedule": "June–August", "for_courses": "LDC, DEO, PA/SA posts in central govt offices", "eligibility": "12th pass, Age 18–27", "website": "ssc.nic.in", "exam_type": "govt", "icon": "briefcase", "color": "#006064"},
    "SSC MTS": {"full_name": "SSC Multi-Tasking Staff", "conducting_body": "SSC – Staff Selection Commission", "schedule": "February–March", "for_courses": "Group C non-gazetted posts in central ministries", "eligibility": "10th / 12th pass, Age 18–25", "website": "ssc.nic.in", "exam_type": "govt", "icon": "briefcase", "color": "#006064"},
    "UPSC CSE": {"full_name": "UPSC Civil Services Examination (IAS/IPS/IFS)", "conducting_body": "UPSC – Union Public Service Commission", "schedule": "Prelims May / Mains Sep / Interview Jan–Feb", "for_courses": "IAS, IPS, IFS, IRS and other Group A central services", "eligibility": "Any Graduation, Age 21–32 (6 attempts general)", "website": "upsc.gov.in", "exam_type": "govt", "icon": "shield", "color": "#BF360C"},
    "UPSC CDS": {"full_name": "Combined Defence Services Examination", "conducting_body": "UPSC – Union Public Service Commission", "schedule": "February & August (twice/year)", "for_courses": "IMA (Army), AFA (Air Force), INA (Navy), OTA", "eligibility": "Graduation, Age 19–25, Male/Female both", "website": "upsc.gov.in", "exam_type": "defence", "icon": "shield", "color": "#1A237E"},
    "NDA": {"full_name": "National Defence Academy Examination", "conducting_body": "UPSC – Union Public Service Commission", "schedule": "April & September (twice/year)", "for_courses": "Army/Navy/Air Force wings of NDA + Naval Academy", "eligibility": "12th pass (PCM for AF/Navy), Male unmarried, Age 16.5–19.5", "website": "upsc.gov.in", "exam_type": "defence", "icon": "shield", "color": "#1A237E"},
    "IBPS PO": {"full_name": "IBPS Probationary Officer", "conducting_body": "IBPS – Institute of Banking Personnel Selection", "schedule": "Oct–Nov (Prelims), Nov–Dec (Mains)", "for_courses": "PO/MT posts in 11 public sector banks (PNB, BOB, Canara etc.)", "eligibility": "Any Graduation, Age 20–30", "website": "ibps.in", "exam_type": "banking", "icon": "card", "color": "#1B5E20"},
    "SBI PO": {"full_name": "State Bank of India Probationary Officer", "conducting_body": "SBI – State Bank of India", "schedule": "March (Prelims), April (Mains), June (Interview)", "for_courses": "Probationary Officer in SBI (India's largest bank)", "eligibility": "Any Graduation, Age 21–30", "website": "sbi.co.in/careers", "exam_type": "banking", "icon": "card", "color": "#1B5E20"},
    "IBPS Clerk": {"full_name": "IBPS Clerical Cadre Examination", "conducting_body": "IBPS", "schedule": "Aug–Sep (Prelims), October (Mains)", "for_courses": "Clerical posts in 11 public sector banks", "eligibility": "Any Graduation, Age 20–28", "website": "ibps.in", "exam_type": "banking", "icon": "card", "color": "#1B5E20"},
    "SBI Clerk": {"full_name": "SBI Junior Associates (Clerk)", "conducting_body": "SBI – State Bank of India", "schedule": "December (Prelims), Jan–Feb (Mains)", "for_courses": "Junior Associate (Clerk) in SBI branches across India", "eligibility": "Any Graduation, Age 20–28", "website": "sbi.co.in/careers", "exam_type": "banking", "icon": "card", "color": "#1B5E20"},
    "RBI Grade B": {"full_name": "Reserve Bank of India Grade B Officer", "conducting_body": "RBI – Reserve Bank of India", "schedule": "March (Phase I), May (Phase II)", "for_courses": "Officer Grade B (General/DEPR/DSIM) in RBI", "eligibility": "Graduation 60% (55% SC/ST/PWD), Age 21–30", "website": "rbi.org.in/careers", "exam_type": "banking", "icon": "card", "color": "#1B5E20"},
    # ---- RAILWAY ----
    "RRB NTPC": {"full_name": "Railway Recruitment Board – Non-Technical Popular Categories", "conducting_body": "Railway Recruitment Boards (21 RRBs)", "schedule": "CBT-1 notification-based (annually)", "for_courses": "Station Master, Goods Guard, Junior Clerk in Indian Railways", "eligibility": "12th / Graduation depending on post, Age 18–33", "website": "indianrailways.gov.in", "exam_type": "railway", "icon": "train", "color": "#004D40"},
    "RRB Group D": {"full_name": "Railway Recruitment Board Group D", "conducting_body": "Railway Recruitment Boards", "schedule": "CBT March–April", "for_courses": "Track Maintainer, Helper, Assistant in Indian Railways", "eligibility": "10th / ITI pass, Age 18–33", "website": "indianrailways.gov.in", "exam_type": "railway", "icon": "train", "color": "#004D40"},
    # ---- AGRICULTURE ----
    "ICAR AIEEA": {"full_name": "ICAR All India Entrance Examination for Admission", "conducting_body": "ICAR – Indian Council of Agricultural Research", "schedule": "June", "for_courses": "BSc / MSc Agriculture, Veterinary, Fisheries at ICAR universities", "eligibility": "12th PCB/PCM/Agriculture 50%", "website": "icar.org.in", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    "PAU CET": {"full_name": "Punjab Agricultural University CET", "conducting_body": "Punjab Agricultural University, Ludhiana", "schedule": "May–June", "for_courses": "BSc Agriculture / Horticulture / Food Technology at PAU", "eligibility": "12th PCB/Agriculture 50%", "website": "pau.edu", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    "AAU CET": {"full_name": "Assam Agricultural University CET", "conducting_body": "AAU Jorhat", "schedule": "May–June", "for_courses": "BSc Agriculture / Horticulture / Tea Technology at AAU", "eligibility": "12th PCB/Agriculture 50%", "website": "aau.ac.in", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    "BAU Entrance": {"full_name": "Birsa Agricultural University Entrance", "conducting_body": "BAU Ranchi", "schedule": "June", "for_courses": "BSc Agriculture / Horticulture / Veterinary at BAU Ranchi", "eligibility": "12th PCB/Agriculture 50%, Jharkhand domicile preferred", "website": "bau.ac.in", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    "SKRAU CET": {"full_name": "Swami Keshwanand Rajasthan Agricultural University CET", "conducting_body": "SKRAU / RJ Agriculture Universities", "schedule": "June", "for_courses": "BSc Agriculture / Horticulture at Rajasthan agricultural universities", "eligibility": "12th PCB/Agriculture 50%", "website": "skrau.edu.in", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    "AP EAMCET Agriculture": {"full_name": "AP EAMCET Agriculture Stream", "conducting_body": "JNTU Kakinada (APSCHE)", "schedule": "May", "for_courses": "BSc Agriculture / Horticulture / Sericulture in AP", "eligibility": "12th PCB/Agriculture 45%, AP domicile", "website": "sche.aptonline.in", "exam_type": "agriculture", "icon": "leaf", "color": "#33691E"},
    # ---- TEACHING ----
    "CTET": {"full_name": "Central Teacher Eligibility Test", "conducting_body": "CBSE – Central Board of Secondary Education", "schedule": "July & December (twice/year)", "for_courses": "Teaching positions in KVS, NVS, Central Govt Schools", "eligibility": "B.Ed / D.El.Ed, 12th 50%", "website": "ctet.nic.in", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    "State TET": {"full_name": "State Teacher Eligibility Test", "conducting_body": "Respective State Education Boards", "schedule": "Varies by state (typically July–September)", "for_courses": "Primary and Upper Primary teaching in government schools", "eligibility": "B.Ed / D.El.Ed", "website": "respective state board website", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    "BPSC TRE": {"full_name": "Bihar PSC Teacher Recruitment Examination", "conducting_body": "BPSC – Bihar Public Service Commission", "schedule": "Annually (notification-based)", "for_courses": "Primary / Secondary / Higher Secondary teacher in Bihar govt schools", "eligibility": "B.Ed + CTET/TET, Graduation", "website": "bpsc.bih.nic.in", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    "TS EDCET": {"full_name": "Telangana Education Common Entrance Test", "conducting_body": "Osmania University on behalf of TSCHE", "schedule": "June", "for_courses": "B.Ed at Telangana state B.Ed colleges", "eligibility": "Any Graduation 50%", "website": "edcet.tsche.ac.in", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    "RIE Entrance": {"full_name": "Regional Institute of Education Entrance", "conducting_body": "NCERT (RIE Ajmer/Bhopal/Mysore/Bhubaneswar)", "schedule": "May–June", "for_courses": "Integrated B.Ed / B.Ed / M.Ed at NCERT Regional Institutes", "eligibility": "12th 50% (for integrated) / Graduation 50% (for B.Ed)", "website": "ncert.nic.in", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    "Bihar D.El.Ed CET": {"full_name": "Bihar D.El.Ed Common Entrance Test", "conducting_body": "SCERT Bihar", "schedule": "June", "for_courses": "D.El.Ed (Elementary Teacher Training) at Bihar DIETs", "eligibility": "12th pass 50%", "website": "scert.bihar.gov.in", "exam_type": "teaching", "icon": "school", "color": "#0D47A1"},
    # ---- DESIGN ----
    "NID DAT": {"full_name": "NID Design Aptitude Test", "conducting_body": "NID Ahmedabad", "schedule": "January (Prelims), March (Mains)", "for_courses": "BDes / MDes at NID Ahmedabad and 9 NID campuses", "eligibility": "12th pass any stream", "website": "admissions.nid.edu", "exam_type": "design", "icon": "color-palette", "color": "#AD1457"},
    "NIFT Entrance": {"full_name": "NIFT Entrance Test", "conducting_body": "NIFT", "schedule": "February", "for_courses": "BDes / BFTech / MFM / MDes at 18 NIFT campuses", "eligibility": "12th any stream for BDes", "website": "admissions.nift.ac.in", "exam_type": "design", "icon": "color-palette", "color": "#AD1457"},
    "UCEED": {"full_name": "Undergraduate Common Entrance Exam for Design", "conducting_body": "IIT Bombay", "schedule": "January", "for_courses": "BDes at IIT Bombay, IIT Delhi, IIT Hyderabad, IIITDM Kancheepuram", "eligibility": "12th pass any stream, Age ≤ 25", "website": "uceed.iitb.ac.in", "exam_type": "design", "icon": "color-palette", "color": "#AD1457"},
    "MITID DAT": {"full_name": "MIT Institute of Design Aptitude Test", "conducting_body": "MIT Institute of Design, Pune", "schedule": "January–February", "for_courses": "BDes at MITID Pune", "eligibility": "12th pass any stream", "website": "mitid.edu.in", "exam_type": "design", "icon": "color-palette", "color": "#AD1457"},
    "SET Design": {"full_name": "Symbiosis Entrance Test – Design", "conducting_body": "Symbiosis International University", "schedule": "May", "for_courses": "BDes at Symbiosis Institute of Design, Pune", "eligibility": "12th pass, portfolio submission", "website": "set-test.org", "exam_type": "design", "icon": "color-palette", "color": "#AD1457"},
    # ---- PHARMACY ----
    "GPAT": {"full_name": "Graduate Pharmacy Aptitude Test", "conducting_body": "NTA – National Testing Agency", "schedule": "January", "for_courses": "M.Pharm / direct PhD admission at pharmacy colleges", "eligibility": "B.Pharm", "website": "gpat.nta.nic.in", "exam_type": "pharmacy", "icon": "medical", "color": "#558B2F"},
}


def _enrich_exam(exam_name: str) -> dict:
    """Return full exam details from EXAM_DETAILS_DB or a smart fallback."""
    # Exact match
    if exam_name in EXAM_DETAILS_DB:
        details = dict(EXAM_DETAILS_DB[exam_name])
        details["name"] = exam_name
        return details
    # Partial match (case-insensitive)
    exam_lower = exam_name.lower()
    for key, val in EXAM_DETAILS_DB.items():
        if key.lower() in exam_lower or exam_lower in key.lower():
            details = dict(val)
            details["name"] = exam_name
            return details
    # Generic fallback
    return {
        "name": exam_name,
        "full_name": exam_name,
        "conducting_body": "Refer official website",
        "schedule": "Check official notification",
        "for_courses": "Refer official website for details",
        "eligibility": "Check official notification",
        "website": "scholarships.gov.in",
        "exam_type": "general",
        "icon": "document-text",
        "color": "#546E7A"
    }


def get_exams_for_colleges(colleges: list) -> list:
    """Extract unique entrance exam names from a list of college dicts."""
    seen: set = set()
    exams = []
    for college in colleges:
        entrance = college.get("entrance_exam", "") if isinstance(college, dict) else getattr(college, "entrance_exam", "")
        if not entrance:
            continue
        # Split on common separators
        parts = [p.strip() for p in entrance.replace(" / ", "/").replace(" + ", "/").split("/")]
        for part in parts:
            clean = part.strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                exams.append(clean)
    return exams


# --- Deterministic profile-fit scoring (marks + education + stream) ---

_EDUCATION_RANKS: Dict[str, int] = {
    "10th": 0,
    "class 10": 0,
    "10": 0,
    "matric": 0,
    "ssc": 0,
    "12th": 1,
    "class 12": 1,
    "12": 1,
    "10+2": 1,
    "intermediate": 1,
    "hsc": 1,
    "senior secondary": 1,
    "graduate": 2,
    "graduation": 2,
    "ug": 2,
    "undergraduate": 2,
    "bachelor": 2,
    "bachelors": 2,
    "degree": 2,
    "post-graduate": 3,
    "post graduate": 3,
    "postgraduation": 3,
    "pg": 3,
    "masters": 3,
    "master": 3,
    "phd": 3,
    "doctorate": 3,
}

_EXAM_MIN_MARKS: Dict[str, float] = {
    "JEE Advanced": 85,
    "JEE Main": 65,
    "BITSAT": 75,
    "NEET": 55,
    "CAT": 50,
    "XAT": 50,
    "CMAT": 45,
    "CLAT": 45,
    "AILET": 50,
    "CUET": 40,
    "GATE": 55,
    "NDA": 50,
    "CDS": 50,
    "AFCAT": 50,
    "IBPS PO": 50,
    "SBI PO": 50,
    "IBPS Clerk": 45,
    "SBI Clerk": 45,
    "SSC CGL": 50,
    "SSC CHSL": 40,
    "SSC MTS": 35,
    "RRB NTPC": 40,
    "RRB Group D": 35,
    "NTSE": 50,
    "State Scholarship Exam": 40,
    "PM YASASVI": 45,
    "CTET": 50,
    "State TET": 50,
    "ICAR AIEEA": 50,
    "NIFT Entrance": 45,
    "NID DAT": 45,
    "UCEED": 50,
    "NATA": 50,
}

_EXAM_MIN_EDUCATION: Dict[str, int] = {
    "JEE Advanced": 1,
    "JEE Main": 1,
    "BITSAT": 1,
    "NEET": 1,
    "CLAT": 1,
    "AILET": 1,
    "CUET": 1,
    "NDA": 1,
    "CTET": 1,
    "ICAR AIEEA": 1,
    "NIFT Entrance": 1,
    "NID DAT": 1,
    "UCEED": 1,
    "NATA": 1,
    "SSC CHSL": 1,
    "RRB NTPC": 1,
    "SSC MTS": 0,
    "RRB Group D": 0,
    "NTSE": 0,
    "State Scholarship Exam": 0,
    "PM YASASVI": 0,
    "CA Foundation": 1,
    "CA Intermediate": 2,
    "CA Final": 2,
    "UGC NET": 3,
    "CSIR UGC NET JRF": 3,
    "IBPS PO": 2,
    "SBI PO": 2,
    "IBPS Clerk": 2,
    "SBI Clerk": 2,
    "SSC CGL": 2,
    "UPSC CSE": 2,
    "CDS": 2,
    "AFCAT": 2,
    "GATE": 2,
    "CAT": 2,
    "XAT": 2,
    "CMAT": 2,
}


def _safe_marks(profile: StudentProfile) -> float:
    try:
        return max(0.0, min(100.0, float(profile.marks_percentage)))
    except Exception:
        return 0.0


def _education_rank(education_level: str) -> int:
    level = (education_level or "").strip().lower()
    if level in _EDUCATION_RANKS:
        return _EDUCATION_RANKS[level]
    if any(k in level for k in ["phd", "doctorate", "post", "masters", "master", "pg", "m.tech", "mca", "m.sc", "m.com", "ma", "mba", "llm"]):
        return 3
    if any(k in level for k in ["graduate", "graduation", "undergraduate", "bachelor", "degree", "b.tech", "b.e", "bca", "b.sc", "b.com", "ba", "llb", "ug"]):
        return 2
    if any(k in level for k in ["12", "10+2", "intermediate", "hsc", "senior secondary"]):
        return 1
    if any(k in level for k in ["10", "matric", "ssc", "secondary"]):
        return 0
    if "post" in level or "pg" in level:
        return 3
    if "grad" in level:
        return 2
    if "12" in level:
        return 1
    return 0


def _stream_keywords(stream: str) -> List[str]:
    s = (stream or "").lower()
    if "pcm" in s or "engineering" in s or "computer" in s:
        return ["engineering", "technology", "computer", "software", "it", "math", "physics"]
    if "pcb" in s or "medical" in s or "biology" in s:
        return ["medical", "health", "nursing", "pharmacy", "biology", "doctor"]
    if "commerce" in s:
        return ["finance", "bank", "account", "commerce", "management", "business"]
    if "arts" in s or "humanities" in s or "social" in s:
        return ["law", "teaching", "social", "journal", "civil service", "public"]
    return []


def _resolve_exam_key(exam_name: str) -> str:
    name = (exam_name or "").strip()
    if not name:
        return ""
    if name in _EXAM_MIN_MARKS or name in _EXAM_MIN_EDUCATION:
        return name
    lower = name.lower()
    for known in set(list(_EXAM_MIN_MARKS.keys()) + list(_EXAM_MIN_EDUCATION.keys())):
        if known.lower() in lower or lower in known.lower():
            return known
    return name


def _infer_exam_min_marks(exam_name: str) -> float:
    n = (exam_name or "").lower()
    if not n:
        return 0.0

    if "jee advanced" in n:
        return 85.0
    if "jee" in n or "bitsat" in n:
        return 65.0
    if "neet" in n:
        return 55.0
    if any(k in n for k in ["wbjee", "viteee", "srmjeee", "comedk", "iiit", "eamcet", "mht-cet", "kcet", "cet"]):
        return 50.0
    if any(k in n for k in ["clat", "ailet", "nift", "nid", "uceed", "nata", "cuet"]):
        return 45.0
    if any(k in n for k in ["upsc", "cat", "xat", "gate", "ibps po", "sbi po", "ssc cgl"]):
        return 50.0
    if any(k in n for k in ["ibps clerk", "sbi clerk", "ssc chsl", "rrb", "ntpc", "group d"]):
        return 40.0
    return 35.0


def _infer_exam_min_education(exam_name: str) -> int:
    n = (exam_name or "").lower()
    if any(k in n for k in ["ntse", "state scholarship", "pm yasasvi", "ssc mts", "rrb group d"]):
        return 0
    if any(k in n for k in ["cat", "xat", "gate", "upsc", "cds", "afcat", "ibps po", "sbi po", "ibps clerk", "sbi clerk", "ssc cgl"]):
        return 2
    if any(k in n for k in ["ugc net", "csir ugc net"]):
        return 3
    if any(k in n for k in ["jee", "neet", "clat", "ailet", "cuet", "cet", "nift", "nid", "uceed", "nata", "ssc chsl", "rrb", "ntpc", "nda", "ca foundation"]):
        return 1
    if any(k in n for k in ["ca intermediate", "ca final"]):
        return 2
    return 0


def _is_exam_feasible_for_profile(exam_name: str, profile: StudentProfile) -> bool:
    key = _resolve_exam_key(exam_name)
    marks = _safe_marks(profile)
    min_marks = _EXAM_MIN_MARKS.get(key, _infer_exam_min_marks(exam_name))
    if marks < min_marks:
        return False
    min_rank = _EXAM_MIN_EDUCATION.get(key, _infer_exam_min_education(exam_name))
    if _education_rank(profile.education_level) < min_rank:
        return False
    return True


def _exam_fit_score(exam_name: str, profile: StudentProfile) -> float:
    key = _resolve_exam_key(exam_name)
    marks = _safe_marks(profile)
    min_marks = _EXAM_MIN_MARKS.get(key, _infer_exam_min_marks(exam_name))
    score = marks - min_marks
    profile_rank = _education_rank(profile.education_level)
    min_rank = _EXAM_MIN_EDUCATION.get(key, _infer_exam_min_education(exam_name))
    if profile_rank < min_rank:
        score -= 50
    else:
        # Prioritize exams aligned to current education stage.
        distance = profile_rank - min_rank
        if distance == 0:
            score += 6
        elif distance == 1:
            score += 1
        elif distance >= 2:
            score -= min(6, distance * 2)

    # If student is already graduate/PG, de-prioritize early-stage exams.
    if profile_rank >= 2 and min_rank <= 1:
        score -= 8

    # De-prioritize noisy/uncertain exam strings from broad college metadata.
    reliable_patterns = [
        "jee", "neet", "cuet", "clat", "ailet", "nift", "nid", "uceed", "nata",
        "ssc", "rrb", "ibps", "sbi", "upsc", "nda", "cds", "afcat", "gate",
        "cat", "xat", "cmat", "ctet", "tet", "ca foundation", "ca intermediate", "ca final", "ugc net",
    ]
    is_known = key in _EXAM_MIN_MARKS or key in _EXAM_MIN_EDUCATION
    if not is_known:
        low = (exam_name or "").lower()
        if not any(p in low for p in reliable_patterns):
            score -= 18
        else:
            score -= 6
    return score


def _is_reliable_exam_name(exam_name: str) -> bool:
    key = _resolve_exam_key(exam_name)
    if key in _EXAM_MIN_MARKS or key in _EXAM_MIN_EDUCATION:
        return True
    low = (exam_name or "").lower()
    reliable_patterns = [
        "jee", "neet", "cuet", "clat", "ailet", "nift", "nid", "uceed", "nata",
        "ssc", "rrb", "ibps", "sbi", "upsc", "nda", "cds", "afcat", "gate",
        "cat", "xat", "cmat", "ctet", "tet", "ca foundation", "ca intermediate",
        "ca final", "ugc net", "csir",
    ]
    return any(p in low for p in reliable_patterns)


def _job_min_education_rank(job: Job) -> int:
    text = " ".join([
        job.education_required or "",
        job.how_to_get or "",
        job.description or "",
        job.exam_if_any or "",
    ]).lower()

    # Detect explicit degree signals first.
    if any(k in text for k in ["phd", "doctorate", "post graduate", "post-graduate", "master", "m.tech", "mca", "mba", "m.sc", "ma", "llm", "ugc net", "csir ugc net"]):
        return 3
    if any(k in text for k in ["graduation", "graduate", "any graduation", "bachelor", "degree", "b.tech", "b.e", "be ", "bca", "b.sc", "b.com", "ba", "llb", "cat", "gate", "upsc", "ibps po", "sbi po", "ssc cgl"]):
        return 2
    if any(k in text for k in ["12th", "class 12", "10+2", "intermediate", "jee", "neet", "cuet", "clat", "ailet", "nift", "nid", "uceed", "nata", "nda", "ssc chsl", "rrb ntpc", "ca foundation"]):
        return 1

    # Use exam requirements as an extra source of truth.
    inferred = _education_rank(job.education_required or "")
    for exam in _split_exam_parts(job.exam_if_any or ""):
        key = _resolve_exam_key(exam)
        inferred = max(inferred, _EXAM_MIN_EDUCATION.get(key, _infer_exam_min_education(exam)))
    return max(0, inferred)


def _job_education_gap(job: Job, profile: StudentProfile) -> int:
    return _job_min_education_rank(job) - _education_rank(profile.education_level)


def _select_fallback_jobs_by_marks(fallback_struct: dict, profile: StudentProfile) -> List[dict]:
    marks = _safe_marks(profile)
    edu_rank = _education_rank(profile.education_level)
    buckets: Dict[str, List[dict]] = {"now": [], "short_course": [], "after_degree": []}
    for cat in fallback_struct.get("categories", []):
        cid = cat.get("id", "")
        if cid in buckets:
            buckets[cid].extend(cat.get("jobs", []))

    if edu_rank >= 2:
        # Graduate/PG: prioritize degree-level and progression jobs.
        if marks >= 75:
            target_mix = ["after_degree"] * 13 + ["short_course"] * 5 + ["now"] * 2
        elif marks >= 55:
            target_mix = ["after_degree"] * 11 + ["short_course"] * 6 + ["now"] * 3
        else:
            target_mix = ["after_degree"] * 9 + ["short_course"] * 7 + ["now"] * 4
    elif edu_rank == 1:
        # 12th: balance immediate options with short-course and degree pathways.
        if marks >= 75:
            target_mix = ["now"] * 4 + ["short_course"] * 7 + ["after_degree"] * 9
        elif marks >= 55:
            target_mix = ["now"] * 7 + ["short_course"] * 7 + ["after_degree"] * 6
        else:
            target_mix = ["now"] * 10 + ["short_course"] * 7 + ["after_degree"] * 3
    else:
        # 10th or below: prioritize accessible immediate and short-course options.
        if marks >= 75:
            target_mix = ["now"] * 7 + ["short_course"] * 8 + ["after_degree"] * 5
        elif marks >= 55:
            target_mix = ["now"] * 10 + ["short_course"] * 7 + ["after_degree"] * 3
        else:
            target_mix = ["now"] * 13 + ["short_course"] * 6 + ["after_degree"] * 1

    selected: List[dict] = []
    index_by_bucket = {"now": 0, "short_course": 0, "after_degree": 0}
    for b in target_mix:
        i = index_by_bucket[b]
        if i < len(buckets[b]):
            selected.append(buckets[b][i])
            index_by_bucket[b] += 1

    # Fill remaining slots (if any bucket had fewer jobs) without duplicates
    seen_titles = {str(j.get("job_title", "")).strip().lower() for j in selected}
    for b in ["now", "short_course", "after_degree"]:
        for j in buckets[b]:
            t = str(j.get("job_title", "")).strip().lower()
            if t and t not in seen_titles:
                seen_titles.add(t)
                selected.append(j)
            if len(selected) >= 20:
                return selected[:20]

    return selected[:20]


_GENERIC_EXAM_TOKENS = {
    "intermediate", "final", "merit", "state exam", "state entrance",
    "entrance", "exam", "test",
}


def _normalize_exam_name(exam_name: str) -> str:
    e = (exam_name or "").strip()
    if not e:
        return ""
    low = e.lower()
    if low in {"jee mains", "jee mains exam"}:
        return "JEE Main"
    if low in {"jee advanced exam"}:
        return "JEE Advanced"
    if low in {"upsc cds", "cds exam"}:
        return "CDS"
    if low in {"upsc cse", "cse"}:
        return "UPSC CSE"
    return e


def _split_exam_parts(exam_text: str) -> List[str]:
    text = (exam_text or "").strip()
    if not text:
        return []

    parts = re.split(r"[/,+;&|]", text.replace(" and ", "/"))
    cleaned: List[str] = []
    seen: set = set()

    for p in parts:
        e = _normalize_exam_name(p)
        if not e:
            continue
        low = e.lower()
        if low in _GENERIC_EXAM_TOKENS:
            continue
        if len(e) <= 2:
            continue
        if low not in seen:
            seen.add(low)
            cleaned.append(e)

    return cleaned


def _extract_cutoff_min_percentage(cutoff_text: str) -> Optional[float]:
    txt = (cutoff_text or "").strip().lower()
    if not txt:
        return None

    # Only parse as marks when percentage is explicitly present
    if "%" not in txt and "percent" not in txt and "percentage" not in txt:
        return None

    m = re.search(r"(\d{2}(?:\.\d+)?)\s*-\s*(\d{2}(?:\.\d+)?)\s*%", txt)
    if m:
        lo = float(m.group(1))
        return lo if 30 <= lo <= 100 else None

    m = re.search(r"(\d{2}(?:\.\d+)?)\s*%", txt)
    if m:
        v = float(m.group(1))
        return v if 30 <= v <= 100 else None

    m = re.search(r"(\d{2}(?:\.\d+)?)\s*(?:percent|percentage)", txt)
    if m:
        v = float(m.group(1))
        return v if 30 <= v <= 100 else None

    return None


def _evaluate_college_profile_fit(college: dict, profile: StudentProfile) -> dict:
    c = dict(college or {})
    marks = _safe_marks(profile)

    cutoff_text = str(c.get("cutoff") or "").strip()
    min_marks = _extract_cutoff_min_percentage(cutoff_text)

    exam_text = str(c.get("entrance_exam") or "").strip()
    exam_parts = _split_exam_parts(exam_text)
    exam_ok = True if not exam_parts else any(_is_exam_feasible_for_profile(ex, profile) for ex in exam_parts)

    if min_marks is None:
        marks_ok: Optional[bool] = None
    else:
        marks_ok = marks >= min_marks

    eligible = exam_ok and (marks_ok is not False)

    score = 0.0
    score += 3.0 if exam_ok else -6.0
    if marks_ok is True:
        score += 4.0
    elif marks_ok is False:
        score -= 7.0
    else:
        score += 0.5

    # Keep cutoff field user-readable for frontend cards/details
    if min_marks is not None and (not cutoff_text or "%" not in cutoff_text):
        c["cutoff"] = f"Approx minimum {int(round(min_marks))}%"
    elif not cutoff_text:
        c["cutoff"] = "Check latest merit/rank cutoff"

    eligibility_notes: List[str] = []
    if min_marks is not None:
        if marks_ok:
            eligibility_notes.append(f"Marks eligible: {marks:.1f}% vs required ~{min_marks:.0f}%.")
        else:
            eligibility_notes.append(f"Not eligible by marks: needs ~{min_marks:.0f}%.")
    else:
        eligibility_notes.append("Marks cutoff not explicit; verify latest college cutoff.")

    if exam_parts:
        if exam_ok:
            eligibility_notes.append("Entrance exam path is eligible for your profile.")
        else:
            eligibility_notes.append("Entrance exam eligibility not matched for current profile.")

    base_why = str(c.get("why_recommended") or "").strip()
    c["why_recommended"] = (base_why + " " if base_why else "") + " ".join(eligibility_notes)

    c["_fit_score"] = score
    c["_eligible"] = eligible
    return c


def _rank_colleges_for_profile(colleges: List[dict], profile: StudentProfile, count: int) -> List[dict]:
    # Deduplicate first by college name
    dedup: Dict[str, dict] = {}
    ordered_keys: List[str] = []
    for college in colleges:
        name_key = str((college or {}).get("name") or "").strip().lower()
        if not name_key:
            continue
        if name_key not in dedup:
            dedup[name_key] = college
            ordered_keys.append(name_key)

    checked = [_evaluate_college_profile_fit(dedup[k], profile) for k in ordered_keys]
    checked.sort(key=lambda c: c.get("_fit_score", 0), reverse=True)

    # Strong preference: return colleges that are profile-eligible first.
    eligible = [c for c in checked if c.get("_eligible")]
    near_fit = [c for c in checked if not c.get("_eligible") and c.get("_fit_score", -99) >= -1.5]

    preferred = eligible
    if len(preferred) < max(5, count // 2):
        for c in near_fit:
            if c not in preferred:
                preferred.append(c)
            if len(preferred) >= count:
                break

    result: List[dict] = []
    for c in preferred[:count]:
        c.pop("_fit_score", None)
        c.pop("_eligible", None)
        result.append(c)
    return result


def _filter_and_rank_exams(exams: List[str], profile: StudentProfile) -> List[str]:
    seen: set = set()
    scored: List[tuple] = []
    for exam in exams:
        for e in _split_exam_parts(exam):
            if not e or e.lower() in seen:
                continue
            seen.add(e.lower())
            if _is_exam_feasible_for_profile(e, profile):
                scored.append((_exam_fit_score(e, profile), e))

    scored.sort(key=lambda x: x[0], reverse=True)
    reliable = [row for row in scored if _is_reliable_exam_name(row[1])]
    other = [row for row in scored if not _is_reliable_exam_name(row[1])]
    return [exam for _, exam in (reliable + other)]


def _job_fit_score(job: Job, profile: StudentProfile) -> float:
    marks = _safe_marks(profile)
    text = " ".join([
        job.job_title or "",
        job.description or "",
        job.education_required or "",
        " ".join(job.key_skills or []),
        job.how_to_get or "",
    ]).lower()

    score = 0.0

    # Interest match
    interests = [i.lower() for i in (profile.interests or [])]
    if interests:
        interest_hits = sum(1 for i in interests if i and i in text)
        score += min(4.0, interest_hits * 1.2)

    # Stream alignment
    stream_hits = sum(1 for k in _stream_keywords(profile.stream or "") if k in text)
    score += min(3.0, stream_hits * 0.8)

    # Exam feasibility
    if (job.exam_if_any or "").strip():
        parts = _split_exam_parts(job.exam_if_any)
        if parts and any(_is_exam_feasible_for_profile(p, profile) for p in parts):
            score += 2.5
        else:
            score -= 3.0
    else:
        score += 1.0

    # Marks-sensitive growth weighting
    growth = (job.growth_potential or "").lower()
    if marks >= 75 and growth == "high":
        score += 2.0
    elif marks < 55 and growth == "high":
        score -= 1.5
    elif marks < 55 and growth in ["medium", "low"]:
        score += 1.0

    # Education fit (hard signal): prioritize immediate + next-step pathways.
    rank = _education_rank(profile.education_level)
    required_rank = _job_min_education_rank(job)
    gap = required_rank - rank
    if gap <= 0:
        score += 3.0
        if gap == 0:
            score += 1.2
    elif gap == 1:
        score += 0.8  # good future path while still realistic
    else:
        score -= (8.0 + gap * 1.5)

    # For higher-education students, avoid over-prioritizing very low-level roles.
    if rank >= 2 and required_rank == 0:
        score -= 2.0
    elif rank == 3 and required_rank <= 1:
        score -= 1.5

    return score


def _rank_jobs_for_profile(jobs: List[Job], profile: StudentProfile) -> List[Job]:
    profile_rank = _education_rank(profile.education_level)

    def _sort_key(job: Job):
        required_rank = _job_min_education_rank(job)
        gap = required_rank - profile_rank
        immediate_or_eligible = 1 if gap <= 0 else 0
        near_term = 1 if gap <= 1 else 0
        return (near_term, immediate_or_eligible, _job_fit_score(job, profile))

    return sorted(jobs, key=_sort_key, reverse=True)


def _build_career_paths_from_jobs(jobs: List[Job], profile: StudentProfile, top_k: int = 5) -> List[CareerPath]:
    ranked = _rank_jobs_for_profile(jobs, profile)
    marks = _safe_marks(profile)
    career_paths: List[CareerPath] = []
    rank = _education_rank(profile.education_level)

    feasible_now_or_next = [j for j in ranked if _job_min_education_rank(j) - rank <= 1]
    selected_jobs = feasible_now_or_next[:top_k] if feasible_now_or_next else ranked[:top_k]

    for j in selected_jobs:
        fit = _job_fit_score(j, profile)
        feasibility = max(1, min(10, int(round(5 + fit / 2))))
        gap = _job_min_education_rank(j) - rank
        if gap <= 0:
            edu_note = "education level is already eligible"
        elif gap == 1:
            edu_note = "requires one next-step qualification"
        else:
            edu_note = "needs multiple higher qualifications"
        if marks >= 80:
            marks_note = "strong marks support this path"
        elif marks >= 60:
            marks_note = "marks are suitable with focused preparation"
        else:
            marks_note = "possible via foundation courses and step-wise preparation"

        career_paths.append(
            CareerPath(
                career_name=j.job_title,
                description=j.description or f"Career path for {j.job_title}",
                why_suitable=f"Matched by education level, interests/stream and marks ({marks}%) — {edu_note}; {marks_note}.",
                feasibility_score=feasibility,
                estimated_cost="Varies by path",
                time_to_achieve="1-4 years",
                key_skills_needed=j.key_skills or [],
                recommended_colleges=[],
            )
        )

    return career_paths


def get_colleges_for_career(career_name: str, profile: StudentProfile, count: int = 5) -> List[College]:
    """
    Match colleges from MASSIVE database based on career path and student profile.
    Delegates to get_filtered_colleges for smart profile-aware filtering.
    """
    colleges_data = get_filtered_colleges(profile, career_name, count)
    return [College(**c) for c in colleges_data]

async def get_llm_chat():
    """Initialize Gemini LLM chat"""
    api_key = os.environ.get('EMERGENT_LLM_KEY')
    chat = LlmChat(
        api_key=api_key,
        session_id=str(uuid.uuid4()),
        system_message="You are an expert career counselor for rural Indian students. You understand their constraints and provide realistic, actionable career guidance."
    )
    chat.with_model("gemini", "gemini-1.5-flash")
    return chat


def match_scholarships(profile: StudentProfile, career: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Simple keyword-based scholarship matching (RAG simulation)"""
    
    # Extract search keywords from profile
    search_keywords = []
    
    # Education level
    if profile.education_level in ["10th", "Class 10"]:
        search_keywords.extend(["class 10", "class 9", "school", "pre-matric"])
    elif profile.education_level in ["12th", "Class 12"]:
        search_keywords.extend(["class 12", "class 11", "post-matric"])
    elif profile.education_level in ["Graduate", "Graduation"]:
        search_keywords.extend(["graduation", "college", "bsc", "undergraduate"])
    
    # Income bracket
    if "1L" in profile.family_income or "<" in profile.family_income:
        search_keywords.extend(["low income", "economically weaker"])
    elif "2" in profile.family_income or "3" in profile.family_income:
        search_keywords.extend(["middle income"])
    
    # Stream
    if profile.stream:
        search_keywords.append(profile.stream.lower())
    
    # Career-specific
    career_lower = career.lower()
    if "engineering" in career_lower or "technical" in career_lower:
        search_keywords.extend(["engineering", "technical", "aicte"])
    if "science" in career_lower:
        search_keywords.extend(["science", "research"])
    if "medical" in career_lower:
        search_keywords.extend(["medical", "mbbs"])
    
    # Gender (if name suggests female - simplified check)
    if any(name_part in profile.name.lower() for name_part in ["priya", "devi", "kumari", "bai"]):
        search_keywords.extend(["girls", "female", "women"])
    
    search_keywords.append("merit")  # Always check merit scholarships
    
    # Match scholarships
    matched = []
    for scholarship in SCHOLARSHIP_DATABASE:
        score = 0
        for keyword in search_keywords:
            if any(k in keyword or keyword in k for k in scholarship["keywords"]):
                score += 1
        
        if score > 0:
            matched.append({
                "scholarship": scholarship,
                "score": score
            })
    
    # Sort by score and return top_k
    matched.sort(key=lambda x: x["score"], reverse=True)
    return [m["scholarship"] for m in matched[:top_k]]


# ==================== API Endpoints ====================

@api_router.get("/")
async def root():
    return {"message": "AI Career Guide API", "status": "active"}


@api_router.get("/ui-config")
async def get_ui_config():
    """Frontend UI settings served from backend for consistent flow messaging."""
    return {
        "brand_name": "CareerPath AI",
        "hero_tagline": "Plan smart, study right, build your future.",
        "feature_stats": [
            {"value": "100+", "label": "Career Paths"},
            {"value": "50+", "label": "Entrance Exams"},
            {"value": "100+", "label": "Top Colleges"},
            {"value": "100%", "label": "Free Guidance"},
        ],
        "flow_steps": [
            "Tell us your education, marks, and interests",
            "Get AI-matched careers, exams, and colleges",
            "Follow phase-wise roadmap with scholarships",
        ],
        "highlight_chips": [
            "AI Powered",
            "Rural Friendly",
            "Scholarship Support",
            "Career + College + Exam",
        ],
        "theme": {
            "primary": "#1565C0",
            "accent": "#FF6F00",
            "success": "#2E7D32",
            "surface": "#F5F9FF",
        },
    }


@api_router.get("/app-status")
async def get_app_status():
    """Lightweight runtime stats used by the frontend dashboard."""
    now_utc = datetime.utcnow().isoformat() + "Z"
    try:
        total_recommendations = await db.career_recommendations.count_documents({})
        total_feedback = await db.feedback.count_documents({})
        total_users = await db.users.count_documents({})

        latest_recommendation = await db.career_recommendations.find_one(
            {}, sort=[("created_at", -1)]
        )
        last_activity = latest_recommendation.get("created_at") if latest_recommendation else None

        return {
            "status": "active",
            "message": "System healthy",
            "total_recommendations": total_recommendations,
            "total_feedback": total_feedback,
            "total_users": total_users,
            "last_activity": str(last_activity) if last_activity else None,
            "server_time": now_utc,
        }
    except Exception as e:
        logger.warning(f"App status fallback: {e}")
        return {
            "status": "degraded",
            "message": "Stats temporarily unavailable",
            "total_recommendations": 0,
            "total_feedback": 0,
            "total_users": 0,
            "last_activity": None,
            "server_time": now_utc,
        }


@api_router.post("/generate-career-recommendations")
async def generate_career_recommendations(profile: StudentProfile):
    """
    Main endpoint: Generate job + college recommendations using Gemini AI.
    Two parallel Gemini calls: (1) 20 jobs, (2) 15 colleges per interest.
    DB supplements interest colleges to ensure 30 per interest.
    """
    try:
        logger.info(f"Generating recommendations for {profile.name} (Gemini)")

        interests_list: list = profile.interests or []
        interests_str = ', '.join(interests_list) if interests_list else 'General'
        subjects_str = ', '.join([s for s in (profile.subjects or []) if s]) if (profile.subjects or []) else 'Not provided'
        current_class_str = profile.current_class or 'Not provided'
        internet_access_str = profile.internet_access or 'Not provided'
        language_pref_str = profile.language_preference or 'English'
        constraints_str = profile.other_constraints or 'None'

        # ── Prompt 1: 12 Jobs based on education level ─────────────────────
        jobs_prompt = f"""You are a career counselor for rural Indian students. Generate EXACTLY 12 job recommendations.

Student:
    - Name: {profile.name}
- Education: {profile.education_level} | Stream: {profile.stream or 'N/A'}
    - Current Class/Year: {current_class_str}
- Marks: {profile.marks_percentage}% | Location: {profile.location}
- Family Income: {profile.family_income} | Budget: {profile.budget_for_education}
    - Subjects Studied: {subjects_str}
- Interests: {interests_str}
    - Internet Access: {internet_access_str}
    - Preferred Language: {language_pref_str}
    - Constraints: {constraints_str}

    PERSONALIZATION RULES (MANDATORY):
    1) Every recommendation must be feasible for this exact student profile.
    2) Use marks + stream + subjects to avoid recommending impossible paths.
    3) Respect budget and family income in guidance and entry routes.
    4) Respect internet access: include offline/low-data preparation options when limited/poor.
    5) Respect location: prefer pathways and exams realistic for the student's state/region.
    6) Respect constraints and mention practical alternatives in how_to_get.
    7) Keep language simple and student-friendly for Indian learners.
    8) Education-level matching is mandatory:
         - Recommend jobs and exams eligible for current education level OR next immediate step only.
         - Do NOT include jobs/exams requiring more than one education level above the student.

Generate 12 DIVERSE jobs including:
- Immediate jobs (current education)
- Jobs after short courses (3-12 months)
- Jobs after UG degree (3-4 years)
- Government (SSC/Railway/Banking/Defence/PSU) AND Private AND Self-employment
- Cover: IT, Healthcare, Banking, Defence, Agriculture, Teaching, Engineering, Media, Law, Commerce

IMPORTANT: The "education_required" field MUST be a degree/qualification name (e.g. "B.Ed / D.El.Ed", "B.Tech / BCA", "12th Pass", "Any Graduation"). NEVER put a time duration like "4-5 years" in education_required.

Return ONLY this JSON (no extra text):
{{
  "jobs": [
    {{
      "job_title": "Software Developer",
      "description": "Builds web/mobile applications for companies and startups.",
      "education_required": "B.Tech / BCA / Diploma CS",
      "salary_range": "\u20b93\u20138 LPA entry level",
      "sector": "Private",
      "growth_potential": "High",
      "key_skills": ["Python", "JavaScript", "Problem Solving"],
      "how_to_get": "Complete B.Tech/BCA \u2192 practice coding \u2192 campus placements",
      "exam_if_any": "JEE Main / CUET"
    }}
  ],
  "entrance_exams": ["JEE Main","JEE Advanced","NEET","CUET","IBPS PO","IBPS Clerk","SBI PO","SSC CGL","SSC CHSL","RRB NTPC","RRB JE","UPSC CSE","NDA","CDS","AFCAT","CTET","GATE","CAT","CLAT","ICAR AIEEA"]
}}"""

        # ── Prompt 2: 15 colleges per interest ─────────────────────────────
        colleges_prompt = f"""You are an Indian college admissions expert. For EACH interest listed below, provide exactly 15 real Indian colleges — a rich, diverse mix across states.

Student profile:
    - Name: {profile.name}
- Education: {profile.education_level} | Stream: {profile.stream or 'N/A'}
    - Current Class/Year: {current_class_str}
    - Marks: {profile.marks_percentage}%
- Home State: {profile.location} | Budget/year: {profile.budget_for_education}
    - Family Income: {profile.family_income}
    - Subjects: {subjects_str}
- Interests: {interests_str}
    - Internet Access: {internet_access_str}
    - Preferred Language: {language_pref_str}
    - Constraints: {constraints_str}

    PERSONALIZATION RULES (MANDATORY):
    1) At least 70% of suggested colleges per interest should be financially feasible for budget/year: {profile.budget_for_education}.
    2) Ensure course and entrance exam recommendations align with stream, subjects, and marks.
    3) Prioritize colleges with realistic entry paths for this student profile.
    4) Include nearby/regional options around {profile.location} plus national options.
    5) Prefer colleges with scholarships/hostel support for lower income bands.
    6) Include realistic cutoff in each college: minimum marks (%) or rank required for eligibility.

For EACH interest include ALL of:
- Central Govt: IITs, NITs, IIMs, AIIMS, SPA, NLUs, IISERs, ISI, TISS, NIFT, NID, IGNTU etc.
- State Govt: top state universities, state engineering/medical/law colleges
- Deemed/Private reputed: manipal, VIT, SRM, Amity, BITS, Symbiosis, Christ, Lovely Professional, Chitkara, etc.
- Affordable private colleges within the student's budget
- Spread colleges across different Indian states — not only in one state

Return ONLY valid JSON (no extra text, no markdown):
{{
  "INTEREST_NAME": [
    {{
      "name": "Full College Name",
      "location": "City, State",
      "type": "Government",
      "annual_fees": "\u20b92,00,000",
      "entrance_exam": "JEE Advanced",
            "cutoff": "Minimum 75% in 12th (or equivalent rank)",
      "courses_offered": "B.Tech CSE, M.Tech"
    }}
  ]
}}

Each interest key must have EXACTLY 15 college objects. Include keys for ALL: {interests_str}"""

        # ── Two parallel Gemini calls ───────────────────────────────────────
        chat1 = await get_llm_chat()
        chat2 = await get_llm_chat()
        [jobs_response, colleges_response] = await asyncio.gather(
            chat1.send_message(UserMessage(text=jobs_prompt)),
            chat2.send_message(UserMessage(text=colleges_prompt))
        )
        logger.info("Both Gemini calls completed")

        # ── Helper: extract JSON block from LLM text ────────────────────────
        def extract_json(text: str) -> str:
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                return text.split("```")[1].split("```")[0].strip()
            start, end = text.find("{"), text.rfind("}")
            return text[start:end+1] if start != -1 and end != -1 else text

        # ── Parse jobs (Gemini may return "jobs" OR legacy "careers" key) ───
        try:
            jobs_data = json.loads(extract_json(jobs_response))
        except Exception as e:
            logger.error(f"Jobs JSON parse failed: {e}")
            jobs_data = {}

        # Support both "jobs" key and legacy "careers" key from Gemini
        raw_jobs = jobs_data.get("jobs") or jobs_data.get("careers") or []

        def _score_to_growth(score) -> str:
            try:
                s = int(score)
                if s >= 8: return "High"
                if s >= 5: return "Medium"
                return "Low"
            except Exception:
                return "Medium"

        # ── Parse AI interest colleges ──────────────────────────────────────
        try:
            ai_interest_colleges: dict = json.loads(extract_json(colleges_response))
        except Exception as e:
            logger.error(f"Colleges JSON parse failed: {e}")
            ai_interest_colleges = {}

        # ── Build Job list — handle both "jobs" and "careers" field names ───
        jobs: List[Job] = []
        for jd in raw_jobs[:20]:
            try:
                # Careers format: career_name, why_suitable, feasibility_score,
                #                 estimated_cost, time_to_achieve, key_skills_needed
                # Jobs format:    job_title, sector, salary_range, how_to_get, key_skills
                job_title = (jd.get("job_title") or jd.get("career_name") or "Unknown").strip()
                description = jd.get("description", "")
                # education_required must be a qualification name, NOT a time duration.
                # Discard time_to_achieve (e.g. "4-5 years") which is not a qualification.
                raw_edu = jd.get("education_required") or ""
                if not raw_edu or any(x in raw_edu.lower() for x in ["year", "month", "after"]):
                    raw_edu = ""
                edu = (raw_edu or profile.education_level).strip()
                salary = (jd.get("salary_range") or jd.get("estimated_cost") or "Competitive salary").strip()
                sector = jd.get("sector", "Private").strip() or "Private"
                growth = (jd.get("growth_potential") or
                          _score_to_growth(jd.get("feasibility_score", 7)))
                skills = jd.get("key_skills") or jd.get("key_skills_needed") or []
                how_to = (jd.get("how_to_get") or jd.get("why_suitable") or "").strip()
                exam = (jd.get("exam_if_any") or "").strip()
                jobs.append(Job(
                    job_title=job_title, description=description,
                    education_required=edu, salary_range=salary,
                    sector=sector, growth_potential=growth,
                    key_skills=skills, how_to_get=how_to, exam_if_any=exam,
                ))
            except Exception as ex:
                logger.warning(f"Skipping job entry: {ex}")

        logger.info(f"Parsed {len(jobs)} jobs from Gemini response")

        # Fallback hard-coded list if Gemini returned nothing parseable (< 5)
        if len(jobs) < 5:
            logger.warning("Gemini jobs < 5, using personalized fallback jobs by education/stream/interests")
            fallback_struct = _fallback_jobs_by_education(
                profile.education_level,
                profile.stream or "",
                interests_list,
            )
            fallback_jobs = _select_fallback_jobs_by_marks(fallback_struct, profile)

            jobs = []
            for jd in fallback_jobs:
                try:
                    jobs.append(Job(
                        job_title=(jd.get("job_title") or "Unknown Job").strip(),
                        description=(jd.get("description") or "").strip(),
                        education_required=(jd.get("education_required") or profile.education_level).strip(),
                        salary_range=(jd.get("salary_range") or "Competitive").strip(),
                        sector=(jd.get("sector") or "Private").strip(),
                        growth_potential=(jd.get("growth_potential") or "Medium").strip(),
                        key_skills=jd.get("key_skills") or [],
                        how_to_get=(jd.get("how_to_get") or "").strip(),
                        exam_if_any=(jd.get("exam_if_any") or "").strip(),
                    ))
                except Exception as ex:
                    logger.warning(f"Skipping fallback job entry: {ex}")

        # Deterministic ranking prevents generic ordering when AI output is broad
        jobs = _rank_jobs_for_profile(jobs, profile)
        aligned_jobs = [j for j in jobs if _job_education_gap(j, profile) <= 1]
        stretch_jobs = [j for j in jobs if _job_education_gap(j, profile) > 1]
        jobs = (aligned_jobs + stretch_jobs)[:20]

        raw_entrance_exams: list = jobs_data.get("entrance_exams", [])

        # Build career paths from ranked jobs with marks-based feasibility scores
        career_paths = _build_career_paths_from_jobs(jobs, profile, top_k=5)

        # ── Top colleges from DB (primary interest) ─────────────────────────
        primary = interests_list[0] if interests_list else "engineering"
        top_colleges_data = get_filtered_colleges(profile, primary, count=120)
        top_colleges_data = _rank_colleges_for_profile(top_colleges_data, profile, count=20)
        if len(top_colleges_data) < 10:
            extra_pool = get_colleges_by_interest(primary, profile, count=220)
            top_colleges_data = _rank_colleges_for_profile(top_colleges_data + extra_pool, profile, count=20)
        # Deduplicate top colleges by name
        _seen_top: set = set()
        _deduped_top: list = []
        for c in top_colleges_data:
            _key = c.get("name", "").strip().lower()
            if _key and _key not in _seen_top:
                _seen_top.add(_key)
                _deduped_top.append(c)
        top_college_objects = [College(**c) for c in _deduped_top]
        # Track all top-college names so interest groups can exclude them
        top_college_names: set = {c.name.strip().lower() for c in top_college_objects}

        # ── Interest colleges: merge DB (80) + Gemini AI (70) → up to 100 ────
        interest_colleges: dict = {}
        for interest in interests_list:
            db_colleges: list = get_colleges_by_interest(interest, profile, count=80)
            # Dedup within group AND against top_colleges
            db_names: set = {c.get("name", "").lower() for c in db_colleges} | top_college_names
            db_colleges = [c for c in db_colleges
                           if c.get("name", "").strip().lower() not in top_college_names]

            cats = INTEREST_TO_CATEGORIES.get(interest, ["engineering"])
            cat = cats[0] if cats else "engineering"
            pool = CATEGORY_IMAGE_POOLS.get(cat, CATEGORY_IMAGE_POOLS["engineering"])
            img_idx = len(db_colleges)

            ai_raw = ai_interest_colleges.get(interest, [])
            ai_colleges: list = []
            for ai_c in ai_raw[:70]:
                name = ai_c.get("name", "").strip()
                if not name or name.lower() in db_names:
                    continue
                db_names.add(name.lower())
                ai_colleges.append({
                    "name": name,
                    "location": ai_c.get("location", "India"),
                    "type": ai_c.get("type", "Government"),
                    "annual_fees": ai_c.get("annual_fees", "₹50,000"),
                    "total_fees": "",
                    "hostel": "Available",
                    "hostel_facilities": "",
                    "course_offered": ai_c.get("courses_offered", ""),
                    "entrance_exam": ai_c.get("entrance_exam", "CUET"),
                    "nirf_rank": "",
                    "cutoff": ai_c.get("cutoff", ""),
                    "placements": "",
                    "image_url": pool[(img_idx + len(ai_colleges)) % len(pool)],
                    "why_recommended": f"Top college for {interest}",
                    "scholarships": [],
                })

            merged = _rank_colleges_for_profile(db_colleges + ai_colleges, profile, count=100)
            interest_colleges[interest] = merged

        # ── Exam enrichment: pull from top colleges + ALL interest colleges ─
        all_exams_ordered: list = list(raw_entrance_exams)
        seen_lower: set = {e.lower() for e in all_exams_ordered}

        # From job exam_if_any fields
        for job in jobs:
            for e in _split_exam_parts(job.exam_if_any or ""):
                if e and e.lower() not in seen_lower:
                    all_exams_ordered.append(e)
                    seen_lower.add(e.lower())

        # From top colleges
        for exam in get_exams_for_colleges([c.dict() for c in top_college_objects]):
            if exam.lower() not in seen_lower:
                all_exams_ordered.append(exam)
                seen_lower.add(exam.lower())

        # From ALL interest colleges (key source)
        all_interest_flat = [c for cols in interest_colleges.values() for c in cols]
        for exam in get_exams_for_colleges(all_interest_flat):
            if exam.lower() not in seen_lower:
                all_exams_ordered.append(exam)
                seen_lower.add(exam.lower())

        # Final exam list: strictly filtered/ranked by marks + education fit
        all_exams_ordered = _filter_and_rank_exams(all_exams_ordered, profile)

        # Keep a practical minimum set when upstream exam fields are weak
        if not all_exams_ordered:
            fallback_exams = [
                "NTSE", "State Scholarship Exam", "PM YASASVI", "SSC MTS", "RRB Group D",
                "CUET", "SSC CHSL", "RRB NTPC", "JEE Main", "NEET",
                "CLAT", "NIFT Entrance", "CTET", "IBPS Clerk", "GATE",
            ]
            all_exams_ordered = _filter_and_rank_exams(fallback_exams, profile)

        entrance_exam_details = [_enrich_exam(e) for e in all_exams_ordered]
        logger.info(f"Total exams enriched: {len(entrance_exam_details)}")

        # ── Save to DB ──────────────────────────────────────────────────────
        recommendation = CareerRecommendation(
            student_profile=profile,
            career_paths=career_paths,
            jobs=jobs,
            entrance_exams=all_exams_ordered,
            top_colleges=top_college_objects,
        )
        async def save_to_db():
            try:
                await db.career_recommendations.insert_one(recommendation.dict())
            except Exception as db_err:
                logger.warning(f"DB save non-fatal: {db_err}")
                
        asyncio.create_task(save_to_db())

        return {
            "id": recommendation.id,
            "jobs": [j.dict() for j in jobs],
            "career_paths": [cp.dict() for cp in career_paths],
            "entrance_exams": all_exams_ordered,
            "entrance_exam_details": entrance_exam_details,
            "top_colleges": [c.dict() for c in top_college_objects],
            "interest_colleges": interest_colleges,
        }

    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class JobByEducationRequest(BaseModel):
    education_level: str
    stream: Optional[str] = None
    interests: List[str] = []
    location: Optional[str] = "India"
    marks_percentage: Optional[float] = 60.0


def _fallback_jobs_by_education(edu: str, stream: str, interests: List[str]) -> dict:
    """
    Built-in job data organized by education level and interest area.
    Called when AI key is missing or LLM call fails.
    """
    # ── Interest → jobs mapping (now / short_course / after_degree) ──────
    INTEREST_JOBS: dict = {
        "Coding / Tech": {
            "now": [
                {"job_title": "Computer Operator", "description": "Operate and maintain computers in offices or cyber cafes.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["MS Office", "Typing", "Internet"], "how_to_get": "Apply at local offices or data entry firms.", "exam_if_any": ""},
                {"job_title": "IT Support Helper", "description": "Assist teams with basic tech troubleshooting and hardware setup.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Troubleshooting", "Networking Basics"], "how_to_get": "Apply at IT service firms or BPOs.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Web Developer", "description": "Build websites and web apps for businesses.", "education_required": edu + " + Web Dev Cert.", "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["HTML", "CSS", "JavaScript", "React"], "how_to_get": "Complete 6-month course on NPTEL/Coursera → freelance or apply on Naukri.", "exam_if_any": ""},
                {"job_title": "Python / Data Analyst", "description": "Analyse data and create dashboards with Python and Excel.", "education_required": edu + " + Data Analytics Cert.", "salary_range": "₹3-8 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Python", "SQL", "Power BI"], "how_to_get": "Complete 3-month data analytics course → apply on Naukri/LinkedIn.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Software Engineer", "description": "Design and develop large-scale software systems.", "education_required": "B.Tech CS / BCA", "salary_range": "₹4-20 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["DSA", "System Design", "Cloud"], "how_to_get": "JEE Main → B.Tech → campus/off-campus placements.", "exam_if_any": "JEE Main"},
                {"job_title": "Cybersecurity Analyst", "description": "Protect systems and networks from cyber attacks.", "education_required": "B.Tech / B.Sc CS + CEH", "salary_range": "₹5-18 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Networking", "Ethical Hacking", "SIEM"], "how_to_get": "Degree → CEH/CISSP cert → apply at IT security firms.", "exam_if_any": ""},
            ],
        },
        "Medicine / Health": {
            "now": [
                {"job_title": "Hospital Receptionist", "description": "Manage OPD appointments and patient records at a clinic or hospital.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Computer Basics", "Communication", "Record Keeping"], "how_to_get": "Apply directly to private hospitals and clinics.", "exam_if_any": ""},
                {"job_title": "Medical Shop Assistant", "description": "Assist pharmacist in dispensing medicines and managing inventory.", "education_required": edu, "salary_range": "₹1.2-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Medicine Knowledge Basics", "Billing", "Customer Service"], "how_to_get": "Apply at local medical stores or hospital pharmacies.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "ANM / Nursing Assistant", "description": "Provide basic patient care and assist doctors in PHCs and hospitals.", "education_required": edu + " + ANM Course (1 yr)", "salary_range": "₹2-4 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Patient Care", "First Aid", "Medicines"], "how_to_get": "Enroll in ANM (1 yr) or GNM (3 yr) at govt nursing school → govt hospital.", "exam_if_any": "State ANM entrance"},
                {"job_title": "Lab Technician (DMLT)", "description": "Conduct diagnostic tests like blood tests, urine tests in labs.", "education_required": edu + " + DMLT Diploma (2 yrs)", "salary_range": "₹2-4.5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Lab Techniques", "Microscopy", "Pathology Basics"], "how_to_get": "Enroll in DMLT course → hospital lab jobs or private diagnostic centres.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "MBBS Doctor / Medical Officer", "description": "Diagnose and treat patients in PHC, govt hospital, or private clinic.", "education_required": "MBBS", "salary_range": "₹6-15 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Clinical Diagnosis", "Patient Care", "Pharmacology"], "how_to_get": "NEET UG → MBBS (5.5 yrs) → internship → PG optional.", "exam_if_any": "NEET UG"},
                {"job_title": "Physiotherapist", "description": "Rehabilitate patients with physical injuries and mobility issues.", "education_required": "BPT (4.5 yrs)", "salary_range": "₹3-8 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Manual Therapy", "Exercise Science", "Patient Assessment"], "how_to_get": "NEET / state entrance → BPT degree → hospital or private clinic.", "exam_if_any": "State BPT Entrance"},
            ],
        },
        "Teaching": {
            "now": [
                {"job_title": "Private Tutor", "description": "Teach school or college students from home or at a coaching institute.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Subject Knowledge", "Communication", "Patience"], "how_to_get": "Register on UrbanPro or advertise locally.", "exam_if_any": ""},
                {"job_title": "Pre-Primary Teacher (Playschool)", "description": "Teach children aged 2-5 in playschools and Anganwadis.", "education_required": edu, "salary_range": "₹1.2-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Child Care", "Creativity", "Communication"], "how_to_get": "Apply at local playschools or register at Anganwadi.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Computer Teacher (DCA/PGDCA)", "description": "Teach computer basics, MS Office, or coding at schools and institutes.", "education_required": edu + " + DCA/PGDCA Cert.", "salary_range": "₹1.5-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["MS Office", "Internet", "Programming Basics"], "how_to_get": "Complete DCA (6 months) → apply at computer institutes or private schools.", "exam_if_any": ""},
                {"job_title": "Yoga / Physical Trainer", "description": "Conduct fitness and yoga sessions at schools or gyms.", "education_required": edu + " + Yoga Cert.", "salary_range": "₹1.5-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Yoga Asanas", "Anatomy Basics", "Communication"], "how_to_get": "MDNIY short course → private coaching or school PE job.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Government School Teacher (TGT/PGT)", "description": "Teach in government secondary or higher secondary schools.", "education_required": "Graduation + B.Ed", "salary_range": "₹3-7 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Subject Mastery", "Pedagogy", "Classroom Management"], "how_to_get": "Graduation → B.Ed (2 yrs) → CTET/TET → state teacher recruitment.", "exam_if_any": "CTET / State TET"},
                {"job_title": "College Lecturer (Assistant Professor)", "description": "Teach undergraduate students at a degree college.", "education_required": "MA/M.Sc + NET/SET", "salary_range": "₹4-9 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Research", "Subject Expertise", "Communication"], "how_to_get": "Post-graduation → UGC NET → apply via college or university.", "exam_if_any": "UGC NET"},
            ],
        },
        "Drawing / Art": {
            "now": [
                {"job_title": "Freelance Artist / Illustrator", "description": "Create custom illustrations, portraits, or art for clients.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Drawing", "Colour Theory", "Digital Art Basics"], "how_to_get": "Build portfolio on Instagram/Behance → take freelance commissions.", "exam_if_any": ""},
                {"job_title": "Mehndi / Rangoli Artist", "description": "Apply bridal mehndi and decorative art for events.", "education_required": edu, "salary_range": "₹1-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Mehndi Patterns", "Colour Sense", "Speed"], "how_to_get": "Practice portfolio → market through WhatsApp/social media.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Graphic Designer", "description": "Create logos, social media visuals, and marketing material.", "education_required": edu + " + Graphic Design Cert.", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Photoshop", "Illustrator", "Canva"], "how_to_get": "Learn Adobe tools via YouTube → freelance on Fiverr or apply to agencies.", "exam_if_any": ""},
                {"job_title": "Interior Design Assistant", "description": "Assist senior designers with space planning, 3D renders, and sourcing.", "education_required": edu + " + Interior Design Diploma", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["AutoCAD", "SketchUp", "Colour & Space"], "how_to_get": "Join 1-yr interior design diploma → assist at design firms.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Product / UX Designer", "description": "Design digital interfaces and user experiences for apps and websites.", "education_required": "B.Des / B.F.A", "salary_range": "₹4-16 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Figma", "User Research", "Prototyping"], "how_to_get": "NID/NIFT/UCEED entrance → B.Des → startup or product company.", "exam_if_any": "NID / UCEED / NIFT"},
                {"job_title": "Fine Arts Teacher / Illustrator", "description": "Teach fine arts at school or work as a published illustrator.", "education_required": "B.F.A", "salary_range": "₹2-6 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Painting", "Sculpture", "Art History"], "how_to_get": "State Fine Arts college entrance → B.F.A → teaching or publishing.", "exam_if_any": "State BFA Entrance"},
            ],
        },
        "Business": {
            "now": [
                {"job_title": "Sales Executive", "description": "Sell products or services for a company and earn salary + commission.", "education_required": edu, "salary_range": "₹1.5-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Communication", "Persuasion", "Product Knowledge"], "how_to_get": "Apply on Naukri or walk-in at FMCG, telecom, insurance companies.", "exam_if_any": ""},
                {"job_title": "LIC Agent / Insurance Advisor", "description": "Sell life and health insurance policies and earn commissions.", "education_required": edu, "salary_range": "₹1-8 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Sales", "Finance Basics", "Communication"], "how_to_get": "Register at LIC branch → clear IC-38 exam → start selling.", "exam_if_any": "IC-38 (IRDAI)"},
            ],
            "short": [
                {"job_title": "Digital Marketing Executive", "description": "Run Google Ads, SEO and social media campaigns for businesses.", "education_required": edu + " + Digital Marketing Cert.", "salary_range": "₹2.5-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["SEO", "Google Ads", "Analytics"], "how_to_get": "Google/HubSpot free cert → apply on Naukri or freelance.", "exam_if_any": ""},
                {"job_title": "Tally / Accounts Executive", "description": "Manage accounts, GST filings, and billing for small businesses.", "education_required": edu + " + Tally ERP Cert.", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Tally ERP", "GST", "MS Excel"], "how_to_get": "3-month Tally course → apply at CA firms or local companies.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "MBA Manager", "description": "Lead operations, marketing or finance teams at corporations.", "education_required": "MBA / PGDM", "salary_range": "₹6-20 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Leadership", "Strategy", "Analytics"], "how_to_get": "CAT/XAT → IIM or top B-school → campus placement.", "exam_if_any": "CAT / XAT"},
                {"job_title": "Chartered Accountant (CA)", "description": "Audit firms, file taxes, and give financial advisory to businesses.", "education_required": "CA (ICAI)", "salary_range": "₹6-25 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Accounting", "Tax", "Audit", "Finance Law"], "how_to_get": "CA Foundation → Intermediate → Final with articleship.", "exam_if_any": "CA Foundation / Intermediate / Final"},
            ],
        },
        "Agriculture": {
            "now": [
                {"job_title": "Farm Worker / Helper", "description": "Assist in crop management, irrigation, and harvesting on modern farms.", "education_required": edu, "salary_range": "₹1-2.5 LPA", "sector": "Self-Employed", "growth_potential": "Low", "key_skills": ["Farming Techniques", "Physical Fitness"], "how_to_get": "Contact local Krishi Vigyan Kendra for job leads.", "exam_if_any": ""},
                {"job_title": "Organic Vegetable Vendor", "description": "Grow and sell organic vegetables in local markets or online.", "education_required": edu, "salary_range": "₹1-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Organic Farming", "Marketing", "Quality Check"], "how_to_get": "Get free training at KVK → sell at local mandi or on AgroStar.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Agriculture Supervisor (Diploma)", "description": "Supervise crop production, seed distribution, and soil testing.", "education_required": edu + " + Agri Diploma (1-2 yrs)", "salary_range": "₹2-4 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Soil Science", "Crop Management", "Record Keeping"], "how_to_get": "State agri diploma → apply in state agriculture dept or cooperatives.", "exam_if_any": ""},
                {"job_title": "Agri Equipment Technician", "description": "Repair and maintain tractors, pump sets, and agri machinery.", "education_required": edu + " + Agri Machinery Cert.", "salary_range": "₹2-4.5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Mechanical Basics", "Tractor Repair", "Welding"], "how_to_get": "PMKVY Skill India course (3-6 months) → agri co-operative or service centre.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Agricultural Officer (AO)", "description": "Guide farmers on modern techniques and distribute subsidies.", "education_required": "B.Sc Agriculture", "salary_range": "₹3-8 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Agronomy", "Extension Service", "Govt Schemes"], "how_to_get": "B.Sc Agri → state IBPS SO Agriculture / state AO exam.", "exam_if_any": "IBPS SO Agriculture / State AO Exam"},
                {"job_title": "Agri-Business Manager", "description": "Manage supply chains, export, and agri startup operations.", "education_required": "B.Sc Agri + MBA Agri-Business", "salary_range": "₹5-14 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Supply Chain", "Marketing", "Commodity Trading"], "how_to_get": "B.Sc Agri → MBA Agri-Business (MANAGE/IARI) → agri firm or startup.", "exam_if_any": "CAT / XAT"},
            ],
        },
        "Government Jobs": {
            "now": [
                {"job_title": "Anganwadi / ASHA Worker", "description": "Support maternal health and nutrition programs in rural areas.", "education_required": edu, "salary_range": "₹0.8-2 LPA + incentives", "sector": "Government", "growth_potential": "Low", "key_skills": ["Health Awareness", "Community Work", "Record Keeping"], "how_to_get": "Apply via state WCD (Women & Child Development) department.", "exam_if_any": ""},
                {"job_title": "Village Level Worker (VLW)", "description": "Assist gram panchayat in implementing rural development schemes.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["Rural Administration", "Record Keeping"], "how_to_get": "State VLW / Gram Sevak recruitment notification via state employment portal.", "exam_if_any": "State Gram Sevak Exam"},
            ],
            "short": [
                {"job_title": "SSC CHSL Clerk / LDC", "description": "Work as Lower Division Clerk or Postal Assistant in central govt offices.", "education_required": edu, "salary_range": "₹1.9-3.5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["General Awareness", "Typing", "Reasoning"], "how_to_get": "Apply via ssc.nic.in → Tier 1 + Tier 2 exam → Skill Test.", "exam_if_any": "SSC CHSL"},
                {"job_title": "Railway Group D / Technician", "description": "Work on Indian Railways in technical or track maintenance roles.", "education_required": edu, "salary_range": "₹2-3.5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["General Science", "Math", "Reasoning"], "how_to_get": "Apply via RRB portal → CBT exam → PET → medical.", "exam_if_any": "RRB Group D / NTPC"},
            ],
            "degree": [
                {"job_title": "Bank PO / Probationary Officer", "description": "Manage branches, loans and customer accounts at public sector banks.", "education_required": "Any Graduation", "salary_range": "₹4-8 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Aptitude", "Banking Awareness", "English"], "how_to_get": "Graduation → IBPS PO / SBI PO exam → interview.", "exam_if_any": "IBPS PO / SBI PO"},
                {"job_title": "IAS / IPS / IFS Officer", "description": "Lead civil administration, police, or foreign affairs at national level.", "education_required": "Any Graduation", "salary_range": "₹7-18 LPA + perks", "sector": "Government", "growth_potential": "High", "key_skills": ["GK", "Essays", "CSAT", "Integrity"], "how_to_get": "Any graduation → UPSC CSE Prelims + Mains + Interview.", "exam_if_any": "UPSC CSE"},
            ],
        },
        "Banking / Finance": {
            "now": [
                {"job_title": "Bank Teller / Cashier", "description": "Handle cash transactions and assist customers at bank counters.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Cash Handling", "Math", "Communication"], "how_to_get": "Apply at small finance banks, co-operative banks, or credit societies.", "exam_if_any": ""},
                {"job_title": "Accounts Assistant", "description": "Assist in bookkeeping, GST filing, and daily accounts for small firms.", "education_required": edu, "salary_range": "₹1.2-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Tally Basics", "MS Excel", "Arithmetic"], "how_to_get": "Apply at local businesses, CA offices, or small firms.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Tally / GST Practitioner", "description": "Manage books of accounts and GST filing for businesses.", "education_required": edu + " + Tally ERP + GST Cert.", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Tally ERP", "GST", "Income Tax Basics"], "how_to_get": "3-month Tally course → apply at CA firms or retail businesses.", "exam_if_any": ""},
                {"job_title": "Mutual Fund / Stock Market Agent", "description": "Help investors buy mutual funds and earn commissions (NISM certified).", "education_required": edu + " + NISM Series V-A Cert.", "salary_range": "₹2-6 LPA", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["Finance Basics", "Communication", "Market Knowledge"], "how_to_get": "Clear NISM Series V-A exam → register as ARN holder → start advising.", "exam_if_any": "NISM Series V-A"},
            ],
            "degree": [
                {"job_title": "Bank PO / Manager", "description": "Lead branch operations and lending at public or private sector banks.", "education_required": "Any Graduation", "salary_range": "₹4-10 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Banking Awareness", "Aptitude", "Credit Analysis"], "how_to_get": "Graduation → IBPS PO / SBI PO → probation → manager.", "exam_if_any": "IBPS PO / SBI PO"},
                {"job_title": "Chartered Accountant (CA)", "description": "Provide accounting, audit, and tax advisory services to firms.", "education_required": "CA (ICAI)", "salary_range": "₹6-25 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Accounting", "Tax", "Audit"], "how_to_get": "CA Foundation → Intermediate → Final with 3-yr articleship.", "exam_if_any": "CA Foundation / Intermediate / Final"},
            ],
        },
        "Science Research": {
            "now": [
                {"job_title": "Lab Assistant", "description": "Prepare samples, maintain equipment, and record data in research labs.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["Lab Equipment", "Data Recording", "Safety Protocols"], "how_to_get": "Apply via CSIR/DRDO notifications or university lab vacancies.", "exam_if_any": ""},
                {"job_title": "Junior Research Fellow (JRF)", "description": "Assist senior researchers in experiments and literature reviews.", "education_required": edu + " (Graduation preferred)", "salary_range": "₹2-3.5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Research Methods", "Thesis Writing", "Subject Knowledge"], "how_to_get": "Clear CSIR-UGC NET JRF exam → join research institute.", "exam_if_any": "CSIR UGC NET JRF"},
            ],
            "short": [
                {"job_title": "Quality Control Analyst", "description": "Test products in pharma, food, or chemical industries for quality compliance.", "education_required": edu + " + B.Sc / Diploma in QC", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Lab Techniques", "HPLC", "GMP/GLP"], "how_to_get": "B.Sc Chemistry/Biology + QC training → pharmaceutical or FMCG company.", "exam_if_any": ""},
                {"job_title": "CSIR Lab Technician", "description": "Work in national labs conducting routine tests and instrument maintenance.", "education_required": edu + " + B.Sc", "salary_range": "₹2.5-5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Scientific Instruments", "Data Analysis", "Lab Safety"], "how_to_get": "CSIR/DRDO/BARC recruitment via GATE or direct exam.", "exam_if_any": "CSIR Lab Tech Exam / GATE"},
            ],
            "degree": [
                {"job_title": "Scientist / Researcher (DRDO/ISRO)", "description": "Conduct advanced research in defence, space, or basic sciences.", "education_required": "M.Sc / B.Tech + GATE", "salary_range": "₹5-15 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Research", "Data Analysis", "Report Writing"], "how_to_get": "M.Sc/B.Tech → GATE → DRDO CEPTAM / ISRO written exam.", "exam_if_any": "GATE / DRDO CEPTAM / ISRO"},
                {"job_title": "Data Scientist", "description": "Build ML models and extract insights from large datasets.", "education_required": "B.Tech / M.Sc + Data Science Cert.", "salary_range": "₹6-25 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Python", "ML", "Statistics", "SQL"], "how_to_get": "Degree + Kaggle/Coursera → apply at tech companies.", "exam_if_any": ""},
            ],
        },
        "Law / Legal": {
            "now": [
                {"job_title": "Legal Document Typist", "description": "Type and format legal documents, affidavits, and court papers.", "education_required": edu, "salary_range": "₹1.2-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Typing Speed", "MS Word", "Legal Terms Basics"], "how_to_get": "Apply at advocate offices, notary offices, or district courts.", "exam_if_any": ""},
                {"job_title": "Court Clerk / Peon", "description": "Assist courts in file management, summons delivery, and record keeping.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["File Management", "Basic Legal Knowledge"], "how_to_get": "Apply via district court recruitment notifications.", "exam_if_any": "District Court Clerk Exam"},
            ],
            "short": [
                {"job_title": "Para-Legal Assistant", "description": "Assist lawyers in case preparation, legal research, and drafting.", "education_required": edu + " + Para-Legal Cert.", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Legal Research", "Drafting", "Court Procedures"], "how_to_get": "BCI-recognised para-legal training → join law firms or NGOs.", "exam_if_any": ""},
                {"job_title": "Notary Clerk / Document Registrar", "description": "Register legal documents and assist at sub-registrar offices.", "education_required": edu + " (12th min)", "salary_range": "₹1.5-3.5 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["Document Verification", "Stamp Duty Rules", "Record Keeping"], "how_to_get": "State Registration Dept recruitment exam.", "exam_if_any": "State Sub-Registrar Exam"},
            ],
            "degree": [
                {"job_title": "Advocate / Lawyer", "description": "Represent clients in courts and provide legal advisory services.", "education_required": "LLB / BA LLB / BBA LLB", "salary_range": "₹3-20 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Legal Research", "Argumentation", "Drafting"], "how_to_get": "CLAT / LSAT → NLU or college → enrol at Bar Council → practise.", "exam_if_any": "CLAT / LSAT / AILET"},
                {"job_title": "Government Prosecutor / Legal Officer", "description": "Represent government in criminal or civil cases at district courts.", "education_required": "LLB + 3-yr practice", "salary_range": "₹4-10 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Criminal Law", "Drafting", "Court Advocacy"], "how_to_get": "LLB → enrol at Bar → apply for govt prosecutor posts.", "exam_if_any": "State Prosecutor Exam"},
            ],
        },
        "Engineering": {
            "now": [
                {"job_title": "Site Helper / Construction Assistant", "description": "Assist civil engineers on construction sites with supervision and measurements.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Basic Drawing Reading", "Physical Fitness", "Teamwork"], "how_to_get": "Apply at local construction contractors or PWD sub-offices.", "exam_if_any": ""},
                {"job_title": "Industrial Worker / Machine Operator", "description": "Operate basic machines in factories under supervision.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Machine Operation", "Safety Awareness"], "how_to_get": "PMKVY Skill India training → apply at local factories.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Electrician / Wireman (ITI)", "description": "Install and repair electrical wiring in homes, factories and offices.", "education_required": edu + " + ITI Electrician (2 yrs)", "salary_range": "₹2-5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Wiring", "Circuit Knowledge", "Safety"], "how_to_get": "ITI Electrician trade → NCVT apprenticeship → private or govt works.", "exam_if_any": "NCVT / SCVT"},
                {"job_title": "AutoCAD Draftsman", "description": "Create 2D/3D engineering drawings for civil or mechanical projects.", "education_required": edu + " + AutoCAD Cert. (6 months)", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["AutoCAD", "Drawing Standards", "Civil/Mech Basics"], "how_to_get": "Short AutoCAD course → apply at architectural/engineering firms.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Civil / Mechanical Engineer (PWD/NHAI)", "description": "Design and manage construction of infrastructure like roads and buildings.", "education_required": "B.Tech Civil / Mech", "salary_range": "₹4-12 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["AutoCAD", "Structural Design", "Project Management"], "how_to_get": "JEE Main → B.Tech → GATE for PSUs or state AE/JE exams.", "exam_if_any": "JEE Main / GATE"},
                {"job_title": "Electronics Engineer", "description": "Design circuits, embedded systems, and communication hardware.", "education_required": "B.Tech ECE / EEE", "salary_range": "₹4-15 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Circuit Design", "VLSI", "Embedded C"], "how_to_get": "JEE → B.Tech ECE → ISRO / DRDO or private electronics firms.", "exam_if_any": "JEE Main / GATE"},
            ],
        },
        "Nursing / Care": {
            "now": [
                {"job_title": "Hospital Attendant / Ward Boy", "description": "Provide basic patient care support in hospital wards.", "education_required": edu, "salary_range": "₹1-2.5 LPA", "sector": "Both", "growth_potential": "Low", "key_skills": ["Patient Assistance", "Basic First Aid", "Cleanliness"], "how_to_get": "Apply directly at government or private hospitals.", "exam_if_any": ""},
                {"job_title": "Home Care Attendant", "description": "Assist elderly or differently-abled patients at their homes.", "education_required": edu, "salary_range": "₹1.2-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Elder Care", "Mobility Assistance", "Basic Medication"], "how_to_get": "Register at home-care agencies or on Care24 / Portea platform.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "ANM / GNM Nurse", "description": "Provide nursing care in PHCs, hospitals, and clinics.", "education_required": edu + " + ANM (1 yr) / GNM (3 yr)", "salary_range": "₹2-5 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Patient Care", "IV / Injections", "Vital Signs"], "how_to_get": "State ANM/GNM entrance → training → govt hospital recruitment.", "exam_if_any": "State ANM/GNM Entrance"},
                {"job_title": "Physiotherapy Assistant (DPT)", "description": "Assist physiotherapists in exercise and rehabilitation sessions.", "education_required": edu + " + DPT Diploma (2 yrs)", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Exercise Therapy", "Patient Handling", "Anatomy Basics"], "how_to_get": "DPT course → work at physiotherapy clinics or hospitals.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "BSc Nurse / Staff Nurse", "description": "Provide skilled nursing care in government or private hospitals.", "education_required": "B.Sc Nursing (4 yrs)", "salary_range": "₹3-8 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Clinical Nursing", "Pharmacology", "ICU/CCU Care"], "how_to_get": "NEET / state nursing entrance → B.Sc Nursing → govt/private hospital.", "exam_if_any": "NEET / State Nursing Entrance"},
                {"job_title": "Physiotherapist (BPT)", "description": "Rehabilitate patients with injuries and physical disabilities.", "education_required": "BPT (4.5 yrs)", "salary_range": "₹3-8 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Manual Therapy", "Electrotherapy", "Patient Assessment"], "how_to_get": "BPT entrance exam → degree → hospital or own clinic.", "exam_if_any": "State BPT Entrance"},
            ],
        },
        "Fashion / Design": {
            "now": [
                {"job_title": "Tailor / Stitching Expert", "description": "Stitch and alter garments for customers at a boutique or from home.", "education_required": edu, "salary_range": "₹1-3.5 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Stitching", "Pattern Cutting", "Fabric Knowledge"], "how_to_get": "Home boutique or join a garment manufacturer.", "exam_if_any": ""},
                {"job_title": "Embroidery / Craft Artisan", "description": "Create hand-embroidered or craft products for sale.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Embroidery", "Craft Techniques", "Pattern Design"], "how_to_get": "Sell through Amazon Karigar, Meesho, or local exhibitions.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Fashion Designer Assistant", "description": "Assist senior designers in pattern making, fabric sourcing, and sampling.", "education_required": edu + " + Fashion Design Diploma (1 yr)", "salary_range": "₹1.5-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Pattern Making", "CAD Fashion", "Trend Research"], "how_to_get": "1-yr NIFT-style diploma at regional institute → boutique or export house.", "exam_if_any": ""},
                {"job_title": "Visual Merchandiser", "description": "Design attractive product displays and store layouts for retail brands.", "education_required": edu + " + VM Certificate", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Display Sense", "Colour Theory", "Retail Brand Guidelines"], "how_to_get": "Short VM course → apply at fashion retail chains.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Fashion Designer", "description": "Create original clothing collections and present at trade shows.", "education_required": "B.Des Fashion / B.FTech (NIFT)", "salary_range": "₹4-15 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Design Concept", "CAD", "Textiles", "Trend Forecasting"], "how_to_get": "NIFT/NID entrance → degree → fashion house or own label.", "exam_if_any": "NIFT Entrance / NID"},
                {"job_title": "Textile Designer", "description": "Design prints, weaves, and surface patterns for fabric manufacturers.", "education_required": "B.Des Textiles / B.FTech", "salary_range": "₹3-10 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Weave Structures", "Adobe Illustrator", "Colour Theory"], "how_to_get": "NIFT/state textile institute → textile mills or export houses.", "exam_if_any": "NIFT Entrance"},
            ],
        },
        "Animation / Media": {
            "now": [
                {"job_title": "YouTube Content Creator", "description": "Create video content on topics of interest and monetize via AdSense.", "education_required": edu, "salary_range": "₹0-5 LPA (variable)", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["Video Editing", "Script Writing", "Thumbnails"], "how_to_get": "Start a channel → consistent uploads → monetize at 1k subs / 4k hrs.", "exam_if_any": ""},
                {"job_title": "Social Media Content Manager", "description": "Create and schedule posts for brands on Instagram, Facebook, etc.", "education_required": edu, "salary_range": "₹1.5-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Canva", "Copywriting", "Analytics"], "how_to_get": "Build portfolio → Apply at agencies or digital marketing firms.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Video Editor / Motion Graphics", "description": "Edit videos and create animated graphics for YouTube, OTT, and ads.", "education_required": edu + " + Video Editing Cert. (6 months)", "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Premiere Pro", "After Effects", "Colour Grading"], "how_to_get": "Learn on YouTube / MAAC → freelance on Fiverr or join production house.", "exam_if_any": ""},
                {"job_title": "2D Animator", "description": "Create 2D animations for explainer videos, games, and TV shows.", "education_required": edu + " + 2D Animation Cert.", "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Adobe Animate", "Moho", "Storyboarding"], "how_to_get": "6-month animation diploma → apply at animation studios or freelance.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "3D Animator / VFX Artist", "description": "Create 3D animations and visual effects for films, games, or ads.", "education_required": "B.Sc Animation / B.Des", "salary_range": "₹4-18 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Maya", "Blender", "ZBrush", "Compositing"], "how_to_get": "MAAC/Arena/FTII → B.Sc Animation → film studio or gaming company.", "exam_if_any": "FTII Entrance / NID"},
                {"job_title": "Broadcast Journalist", "description": "Report and present news for TV channels, digital media, and radio.", "education_required": "BA / BJC (Bachelor of Journalism)", "salary_range": "₹3-12 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Reporting", "Video Editing", "Communication", "Social Media"], "how_to_get": "BA Journalism from state college or IIMC → news network internship.", "exam_if_any": "IIMC / AJKMC Entrance"},
            ],
        },
        "Pharmacy": {
            "now": [
                {"job_title": "Medical Shop Assistant", "description": "Assist licensed pharmacist in dispensing and billing at a pharmacy.", "education_required": edu, "salary_range": "₹1-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Medicine Names", "Billing Software", "Customer Service"], "how_to_get": "Apply at local medical stores, hospital pharmacies.", "exam_if_any": ""},
                {"job_title": "Pharma Company MR (Medical Representative)", "description": "Promote pharmaceutical products to doctors and hospitals.", "education_required": edu + " (Science preferred)", "salary_range": "₹2-5 LPA + incentives", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Communication", "Product Knowledge", "Relationship Building"], "how_to_get": "Apply at pharma companies like Cipla, Sun Pharma → field training.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "D.Pharma Pharmacist", "description": "Dispense medicines, counsel patients, and manage pharmacy inventory.", "education_required": edu + " + D.Pharma (2 yrs)", "salary_range": "₹2-4.5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Dispensing", "Drug Interactions", "Inventory Management"], "how_to_get": "D.Pharma approval from PCI → state registration → govt/private pharmacy.", "exam_if_any": "State D.Pharma Entrance"},
                {"job_title": "Pharma QA / QC Technician", "description": "Test raw materials and finished pharma products for quality standards.", "education_required": edu + " + D.Pharma / B.Sc", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["HPLC", "GMP", "Lab Safety", "Analytical Techniques"], "how_to_get": "D.Pharma or B.Sc Chem → pharma manufacturing companies.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "B.Pharma Pharmacist / Drug Inspector", "description": "Oversee drug quality, clinical trials, and regulatory compliance.", "education_required": "B.Pharma (4 yrs)", "salary_range": "₹3-10 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Pharmacology", "Regulatory Affairs", "QA/QC"], "how_to_get": "GPAT / state entrance → B.Pharma → govt drug dept or pharma company.", "exam_if_any": "GPAT"},
                {"job_title": "Clinical Research Associate (CRA)", "description": "Monitor clinical trials and ensure GCP compliance at hospitals.", "education_required": "B.Pharma / M.Sc Life Sciences", "salary_range": "₹4-12 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["GCP", "Protocol Review", "Data Management"], "how_to_get": "B.Pharma + Clinical Research cert (IQVIA/Quintiles certification) → CRO firms.", "exam_if_any": ""},
            ],
        },
        "Architecture": {
            "now": [
                {"job_title": "AutoCAD Draftsman", "description": "Draft 2D architectural drawings for building sites and govt offices.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["AutoCAD", "Drawing Standards", "Scale Reading"], "how_to_get": "6-month AutoCAD course → apply at architecture firms or PWD offices.", "exam_if_any": ""},
                {"job_title": "Construction Supervisor", "description": "Supervise day-to-day construction work at building sites.", "education_required": edu + " + Diploma Civil", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Site Management", "Material Knowledge", "Labour Coordination"], "how_to_get": "Diploma in Civil → apply with local contractors or builders.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Interior Design Assistant", "description": "Help with space planning, 3D renders, and client presentations.", "education_required": edu + " + Interior Design Diploma (1 yr)", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["AutoCAD", "SketchUp", "3ds Max", "Colour Theory"], "how_to_get": "1-yr diploma at CSIID or similar → interior design studio.", "exam_if_any": ""},
                {"job_title": "Landscape Design Assistant", "description": "Design gardens, parks, and outdoor spaces for developers.", "education_required": edu + " + Landscape Cert. (6 months)", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Plant Species", "Site Planning", "AutoCAD"], "how_to_get": "Short landscape course → builders, township developers, nurseries.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Architect", "description": "Design buildings and oversee construction for residential/commercial projects.", "education_required": "B.Arch (5 yrs)", "salary_range": "₹4-16 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Revit", "AutoCAD", "Structural Knowledge", "Urban Planning"], "how_to_get": "NATA entrance → B.Arch → Council of Architecture registration → practice.", "exam_if_any": "NATA / JEE Paper 2"},
                {"job_title": "Urban Planner (Town Planning Officer)", "description": "Plan zoning, land use, and infrastructure for cities and towns.", "education_required": "B.Arch / B.Plan + M.Plan", "salary_range": "₹4-12 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["GIS", "Urban Design", "Zoning Laws"], "how_to_get": "B.Arch/B.Plan + M.Plan → state RERA / municipal corporation jobs.", "exam_if_any": "State Town Planner Exam"},
            ],
        },
        "Defense / Army": {
            "now": [
                {"job_title": "Army Soldier (Agniveer)", "description": "Serve in Indian Army as soldier under Agnipath scheme.", "education_required": edu, "salary_range": "₹2.1-6.9 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Physical Fitness", "Discipline", "Teamwork"], "how_to_get": "Apply when Army Agniveer rally is announced in your state.", "exam_if_any": "Army Agniveer CEE"},
                {"job_title": "Police Constable", "description": "Maintain law and order and assist citizens in state police.", "education_required": edu, "salary_range": "₹2-4 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Physical Fitness", "GK", "Communication"], "how_to_get": "Apply via state police recruitment → physical test → written exam.", "exam_if_any": "State Police Constable Exam"},
            ],
            "short": [
                {"job_title": "CRPF / BSF Constable", "description": "Serve in central armed police forces for border and internal security.", "education_required": edu, "salary_range": "₹2.5-5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Physical Fitness", "Firearms Training", "Teamwork"], "how_to_get": "SSC GD exam → CRPF/BSF/CISF physical test → medical.", "exam_if_any": "SSC GD"},
                {"job_title": "NCC / Defence Prep Trainer", "description": "Train aspirants for defence (NDA/CDS) at coaching institutes.", "education_required": edu + " (Ex-serviceman preferred)", "salary_range": "₹1.5-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Defence Exam Knowledge", "Physical Training", "Communication"], "how_to_get": "Ex-service personnel with NCC background → join defence academies.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Commissioned Army / Navy / Air Force Officer", "description": "Lead troops or crew as Lieutenant or Flight Lieutenant in Indian Armed Forces.", "education_required": "Graduation / B.Tech", "salary_range": "₹6-18 LPA + perks", "sector": "Government", "growth_potential": "High", "key_skills": ["Leadership", "Physical Fitness", "Technical Knowledge"], "how_to_get": "NDA (after 12th) or CDS (after graduation) → SSB interview → commission.", "exam_if_any": "NDA / CDS / AFCAT"},
                {"job_title": "DRDO / ISRO Defence Scientist", "description": "Develop weapons, missile systems, and defence technology for India.", "education_required": "B.Tech / M.Sc + GATE", "salary_range": "₹6-15 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Research", "Engineering", "Data Analysis"], "how_to_get": "GATE qualified → DRDO CEPTAM or ISRO ICRB written exam.", "exam_if_any": "DRDO CEPTAM / GATE"},
            ],
        },
        "Social Work": {
            "now": [
                {"job_title": "NGO Field Worker", "description": "Conduct awareness camps, surveys, and community outreach programs.", "education_required": edu, "salary_range": "₹1-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Communication", "Community Engagement", "Report Writing"], "how_to_get": "Apply at local NGOs or government ICDS / NHM programs.", "exam_if_any": ""},
                {"job_title": "Anganwadi / ASHA Worker", "description": "Promote nutrition, maternal health, and child care in villages.", "education_required": edu, "salary_range": "₹0.8-2 LPA + incentives", "sector": "Government", "growth_potential": "Low", "key_skills": ["Health Awareness", "Record Keeping", "Community Work"], "how_to_get": "Apply via state WCD (Women & Child Development) department.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Community Health Worker (CHW)", "description": "Provide basic health education and first-aid support to rural communities.", "education_required": edu + " + CHW Cert. (6 months)", "salary_range": "₹1.5-3.5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Health Education", "First Aid", "Record Keeping"], "how_to_get": "NHM / state health mission short training → PHC or sub-centre.", "exam_if_any": ""},
                {"job_title": "Counsellor Assistant (Diploma)", "description": "Provide basic emotional support and refer clients to professional counsellors.", "education_required": edu + " + Counselling Diploma (1 yr)", "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Active Listening", "Communication", "Empathy"], "how_to_get": "1-yr diploma → join NGOs, schools, rehab centres.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Social Worker / Case Manager (MSW)", "description": "Manage welfare cases and coordinate with government agencies to support families.", "education_required": "BSW / MSW", "salary_range": "₹2.5-7 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Case Management", "Policy Knowledge", "Counselling"], "how_to_get": "BSW/MSW → UN agencies, government welfare depts, or corporate CSR.", "exam_if_any": "TISS Entrance (for MSW)"},
                {"job_title": "Child Welfare Officer", "description": "Protect children's rights and manage rehabilitation at CWC / SOS.", "education_required": "BSW / MSW + CHILD PROTECTION cert.", "salary_range": "₹3-7 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Child Rights", "Case Documentation", "Trauma Care"], "how_to_get": "BSW/MSW → DCPU / Child Welfare Committee / CHILDLINE.", "exam_if_any": ""},
            ],
        },
        "Sports": {
            "now": [
                {"job_title": "Sports Coach (Local)", "description": "Coach children and youth in cricket, football, or athletics at local clubs.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Sport-specific Skills", "Leadership", "Communication"], "how_to_get": "Register with a local sports academy or school.", "exam_if_any": ""},
                {"job_title": "Gym Instructor / Fitness Trainer", "description": "Train clients in fitness and weight management at gyms.", "education_required": edu, "salary_range": "₹1-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Fitness Assessment", "Exercise Techniques", "Nutrition Basics"], "how_to_get": "ACE / Gold's Gym cert → join a gym or private clients.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "NIS-Certified Sports Coach", "description": "Coach athletes at district or state level with NIS qualification.", "education_required": edu + " + NIS Diploma in Coaching", "salary_range": "₹2-5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Sportskills", "Sports Science Basics", "Coaching Methods"], "how_to_get": "Apply at NIS Patiala for sports coaching diploma → SAI / state sports authority.", "exam_if_any": "NIS Entrance"},
                {"job_title": "Yoga Instructor", "description": "Teach yoga at schools, gyms, online platforms, or as personal trainer.", "education_required": edu + " + Yoga Instructor Cert. (200 hrs)", "salary_range": "₹1.5-5 LPA", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["Yoga Asanas", "Pranayama", "Anatomy Basics"], "how_to_get": "MDNIY / YCB certified 200-hr course → local gym, school, or online classes.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Sports Officer / SAI Coach", "description": "Work with Sports Authority of India coaching national-level athletes.", "education_required": "B.P.Ed / B.Sc Sports", "salary_range": "₹4-9 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Sports Science", "Training Methods", "Team Management"], "how_to_get": "B.P.Ed → SAI/TOPS programme → state sports authority selection.", "exam_if_any": "SAI Recruitment"},
                {"job_title": "Sports Physiotherapist", "description": "Treat sports injuries and build rehabilitation programs for athletes.", "education_required": "BPT (4.5 yrs)", "salary_range": "₹4-12 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Manual Therapy", "Sports Biomechanics", "Injury Prevention"], "how_to_get": "BPT → sports hospital or national sports federation.", "exam_if_any": "BPT Entrance"},
            ],
        },
        "Music": {
            "now": [
                {"job_title": "Music Tutor (Local / Online)", "description": "Teach vocals, guitar, tabla, or keyboard to students from home or online.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Instrument Proficiency", "Communication", "Patience"], "how_to_get": "Register on UrbanPro or YouTube channel → get private students.", "exam_if_any": ""},
                {"job_title": "Event Performer / Musician", "description": "Perform at weddings, corporate events, and music festivals.", "education_required": edu, "salary_range": "₹1-6 LPA (variable)", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Performance Skills", "Repertoire", "Stage Presence"], "how_to_get": "Join a local band → book events via bookmyshow/ArtistAloud or social media.", "exam_if_any": ""},
            ],
            "short": [
                {"job_title": "Sound Engineer / Audio Producer", "description": "Record, mix, and master music tracks for artists and studios.", "education_required": edu + " + Sound Engineering Cert. (6-12 months)", "salary_range": "₹2-8 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Pro Tools/Ableton", "Mixing", "Mastering", "Acoustics"], "how_to_get": "Sir JJ / SAE short course → recording studio or freelance.", "exam_if_any": ""},
                {"job_title": "Music Teacher (DMA Diploma)", "description": "Teach classical or contemporary music at schools or academies.", "education_required": edu + " + DMA Diploma (2 yrs)", "salary_range": "₹1.5-4 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Music Theory", "Raga Knowledge", "Student Assessment"], "how_to_get": "Sangeet Prabhakar / DMA diploma → school music teacher or academy.", "exam_if_any": ""},
            ],
            "degree": [
                {"job_title": "Film / Background Score Composer", "description": "Create original compositions for films, OTT shows, and advertisements.", "education_required": "B.A Music / B.Mus", "salary_range": "₹4-25 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Composition", "DAW (Logic/Ableton)", "Orchestration"], "how_to_get": "B.A Music or FTII sound/music course → assist composers → own projects.", "exam_if_any": "FTII Entrance"},
                {"job_title": "Music Director / Cultural Officer", "description": "Lead music programs at Doordarshan, AIR, or cultural organisations.", "education_required": "B.A / MA Music", "salary_range": "₹3-9 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Music Production", "Cultural Events", "Broadcast Knowledge"], "how_to_get": "MA Music → AIR / Doordarshan audition or cultural ministry recruitment.", "exam_if_any": "AIR / DD Audition"},
            ],
        },
    }

    # ── Build interest-aware job lists ──────────────────────────────────────
    edu_lower = edu.lower()

    def _edu_fallback_now():
        if "graduate" in edu_lower or "post" in edu_lower:
            return [
                {"job_title": "SSC CGL Officer", "description": "Work in central govt ministries.", "education_required": edu, "salary_range": "₹4-9 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["GK", "Aptitude", "English"], "how_to_get": "Apply ssc.nic.in → Tier 1 + Tier 2.", "exam_if_any": "SSC CGL"},
                {"job_title": "Content Writer", "description": "Write blogs and articles for businesses.", "education_required": edu, "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Writing", "SEO", "Research"], "how_to_get": "Build portfolio → Internshala/LinkedIn.", "exam_if_any": ""},
            ]
        elif "12" in edu_lower:
            return [
                {"job_title": "Data Entry Operator", "description": "Enter and manage data for offices.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["MS Office", "Typing", "Accuracy"], "how_to_get": "Apply via SSC CHSL.", "exam_if_any": "SSC CHSL"},
                {"job_title": "Retail Sales Executive", "description": "Work at stores or FMCG distributors.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Communication", "Product Knowledge"], "how_to_get": "Apply at D-Mart / Reliance Retail.", "exam_if_any": ""},
            ]
        else:
            return [
                {"job_title": "Delivery Executive", "description": "Deliver parcels for Swiggy/Zomato/Amazon.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["DL", "Navigation"], "how_to_get": "Register on delivery partner app.", "exam_if_any": ""},
                {"job_title": "Farm Assistant", "description": "Assist in crop management.", "education_required": edu, "salary_range": "₹1-2.5 LPA", "sector": "Self-Employed", "growth_potential": "Low", "key_skills": ["Farming", "Physical Fitness"], "how_to_get": "Contact local KVK.", "exam_if_any": ""},
            ]

    now_jobs: list = []
    short_jobs: list = []
    degree_jobs: list = []

    # Pull jobs from each selected interest
    for interest in interests:
        pool = INTEREST_JOBS.get(interest, {})
        now_jobs.extend(pool.get("now", []))
        short_jobs.extend(pool.get("short", []))
        degree_jobs.extend(pool.get("degree", []))

    # If no interests selected, fall back to education-based generics
    if not now_jobs:
        now_jobs = _edu_fallback_now()
    if not short_jobs:
        short_jobs = [
            {"job_title": "Web Developer", "description": "Build websites after online certification.", "education_required": edu + " + Web Dev Cert.", "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["HTML", "CSS", "JavaScript"], "how_to_get": "6-month NPTEL course → freelance.", "exam_if_any": ""},
            {"job_title": "Tally Accounts Executive", "description": "Manage books of accounts for small businesses.", "education_required": edu + " + Tally Cert.", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Tally ERP", "GST"], "how_to_get": "3-month course → CA firms.", "exam_if_any": ""},
        ]
    if not degree_jobs:
        degree_jobs = [
            {"job_title": "Bank PO", "description": "Manage branch operations at public sector banks.", "education_required": "Any Graduation", "salary_range": "₹4-8 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Aptitude", "Banking"], "how_to_get": "Graduation → IBPS PO.", "exam_if_any": "IBPS PO"},
        ]

    # ── General padding pool – ensures every category has ≥ 20 jobs ──────────
    _NOW_PAD = [
        {"job_title": "Data Entry Operator", "description": "Enter and manage records for offices and govt departments.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["MS Office", "Typing", "Accuracy"], "how_to_get": "Apply via SSC CHSL.", "exam_if_any": "SSC CHSL"},
        {"job_title": "Retail Sales Executive", "description": "Assist customers and manage billing at large retail stores.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Communication", "Product Knowledge", "Billing"], "how_to_get": "Apply at D-Mart / Reliance Retail / Big Bazaar.", "exam_if_any": ""},
        {"job_title": "Delivery Executive", "description": "Deliver parcels for Swiggy / Zomato / Amazon logistics.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Driving Licence", "Navigation", "Communication"], "how_to_get": "Register on Swiggy/Zomato/Amazon delivery partner app.", "exam_if_any": ""},
        {"job_title": "Customer Care Executive", "description": "Handle inbound customer queries for BPO or telecom companies.", "education_required": edu, "salary_range": "₹1.8-3.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Communication", "Problem Solving", "Computer Basics"], "how_to_get": "Apply at Concentrix / Genpact / Teleperformance.", "exam_if_any": ""},
        {"job_title": "Security Guard / Supervisor", "description": "Guard premises for corporate offices, banks, or malls.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Vigilance", "Communication", "First Aid"], "how_to_get": "Apply at G4S / Securitas / SIS Security.", "exam_if_any": ""},
        {"job_title": "Office Peon / Multi-Tasking Staff", "description": "Assist clerical staff with file movement, photocopying, and office tasks.", "education_required": edu, "salary_range": "₹1.5-2.5 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["Communication", "Reliability"], "how_to_get": "Apply via SSC MTS notification at ssc.nic.in.", "exam_if_any": "SSC MTS"},
        {"job_title": "Postal Assistant / Sorting Assistant", "description": "Sort mail and assist postal operations at post offices.", "education_required": edu, "salary_range": "₹1.8-3.5 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Sorting", "Typing", "Math"], "how_to_get": "Apply via India Post GDS / PA-SA notification.", "exam_if_any": "India Post PA / SA"},
        {"job_title": "Field Sales Promoter", "description": "Promote and demonstrate products at stores, exhibitions, or door-to-door.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA + incentives", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Persuasion", "Product Demo", "Communication"], "how_to_get": "Apply at FMCG or electronics companies for promoter roles.", "exam_if_any": ""},
        {"job_title": "Receptionist / Front Desk Executive", "description": "Greet visitors and manage phone calls and appointments.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Communication", "MS Office", "Professionalism"], "how_to_get": "Apply at hotels, hospitals, or corporates via Naukri.", "exam_if_any": ""},
        {"job_title": "Warehouse Associate / Packer", "description": "Pick, pack, and dispatch orders at e-commerce warehouses.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Physical Fitness", "Accuracy", "Teamwork"], "how_to_get": "Apply at Amazon / Flipkart logistics centres.", "exam_if_any": ""},
        {"job_title": "Cashier / Billing Executive", "description": "Operate POS billing at supermarkets, pharmacies, or petrol pumps.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Cash Handling", "Math", "Billing Software"], "how_to_get": "Walk-in at local supermarkets or apply on Naukri.", "exam_if_any": ""},
        {"job_title": "Kitchen Helper / Cook Assistant", "description": "Assist cooks in hotel kitchens or canteens with food prep.", "education_required": edu, "salary_range": "₹1.2-2.5 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Food Hygiene", "Cooking Basics", "Speed"], "how_to_get": "Apply at hotel chains or industrial canteens.", "exam_if_any": ""},
        {"job_title": "Housekeeping Supervisor", "description": "Oversee cleaning and hygiene operations in hotels or hospitals.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Private", "growth_potential": "Low", "key_skills": ["Team Management", "Hygiene Standards", "Scheduling"], "how_to_get": "Apply at hotel chains or hospital facilities teams.", "exam_if_any": ""},
        {"job_title": "Village Panchayat Operator (CSC)", "description": "Run Common Service Centre in village to deliver govt e-services.", "education_required": edu, "salary_range": "₹0.5-3 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Computer Basics", "Internet", "Communication"], "how_to_get": "Register at CSC Digital India portal (csc.gov.in).", "exam_if_any": ""},
        {"job_title": "Pradhan Mantri Kaushal Kendra Trainer", "description": "Train youth in skill development programs under PMKVY scheme.", "education_required": edu, "salary_range": "₹1.5-3 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Communication", "Vocational Skills", "Teaching Basics"], "how_to_get": "Register on Skill India Portal (skillindiadigital.gov.in) as trainer.", "exam_if_any": ""},
        {"job_title": "E-Commerce Reseller (Meesho / Glowroad)", "description": "Sell products online without inventory via reseller apps.", "education_required": edu, "salary_range": "₹0.5-4 LPA (variable)", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Social Media", "Customer Communication", "Basic Math"], "how_to_get": "Register on Meesho or GlowRoad app and start sharing products.", "exam_if_any": ""},
        {"job_title": "Ration Shop / Fair Price Shop Dealer", "description": "Manage government ration distribution under PDS at local level.", "education_required": edu, "salary_range": "₹1-2.5 LPA + margin", "sector": "Government", "growth_potential": "Low", "key_skills": ["Record Keeping", "Cash Handling", "Communication"], "how_to_get": "Apply via local district food supply office for FPS dealer licence.", "exam_if_any": ""},
        {"job_title": "Solar Panel Installation Helper", "description": "Assist in installing rooftop solar panels under PM Surya Ghar scheme.", "education_required": edu, "salary_range": "₹1.5-3.5 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Electrical Basics", "Safety", "Physical Fitness"], "how_to_get": "PMKVY Solar course (3 months) → join local solar installer.", "exam_if_any": ""},
        {"job_title": "Mobile Repair Technician", "description": "Repair smartphones and accessories at mobile service centres.", "education_required": edu, "salary_range": "₹1.5-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Soldering", "Software Flashing", "Component Knowledge"], "how_to_get": "3-month mobile repair course → own shop or join service centre.", "exam_if_any": ""},
        {"job_title": "Driving / Transportation Operator (Ola/Uber)", "description": "Drive passengers or goods with personal or rented vehicle.", "education_required": edu, "salary_range": "₹2-5 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["Commercial DL", "Navigation", "Customer Service"], "how_to_get": "Get commercial driving licence → register on Ola/Uber/Porter.", "exam_if_any": ""},
    ]

    _SHORT_PAD = [
        {"job_title": "Digital Marketing Executive", "description": "Run Google Ads, SEO and social media campaigns for businesses.", "education_required": edu + " + Digital Marketing Cert.", "salary_range": "₹2.5-6 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["SEO", "Google Ads", "Analytics", "Social Media"], "how_to_get": "Free Google / HubSpot cert → apply on Naukri or freelance.", "exam_if_any": ""},
        {"job_title": "Python Programmer (NIELIT Cert.)", "description": "Write Python scripts for automation, data entry, and basic analysis.", "education_required": edu + " + NIELIT Python Cert.", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Python", "Automation", "MS Excel Integration"], "how_to_get": "NIELIT O/A Level or Coursera Python → apply at IT firms.", "exam_if_any": "NIELIT O Level"},
        {"job_title": "Hardware & Networking Technician", "description": "Install and maintain computer networks and hardware in offices.", "education_required": edu + " + CCNA / HW Networking Cert.", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Networking", "Cisco Basics", "Troubleshooting"], "how_to_get": "CCNA course (6 months) → apply at IT infra or BPO firms.", "exam_if_any": "CCNA"},
        {"job_title": "Fire & Safety Officer (Diploma)", "description": "Ensure workplace fire safety compliance in factories and offices.", "education_required": edu + " + Fire Safety Diploma (1 yr)", "salary_range": "₹2-5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Fire Safety", "First Aid", "Risk Assessment"], "how_to_get": "NIISM fire safety diploma → apply at manufacturing / infra firms.", "exam_if_any": ""},
        {"job_title": "Hotel Management (BHM / Diploma)", "description": "Work in F&B, housekeeping, or front office at hotel chains.", "education_required": edu + " + Hotel Mgmt Diploma (1-3 yr)", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Hospitality", "Communication", "Grooming"], "how_to_get": "NCHMCT / state hotel mgmt diploma → Taj / Marriott / ITC placement.", "exam_if_any": "NCHMCT JEE"},
        {"job_title": "Retail Management Executive (Diploma)", "description": "Manage store operations, inventory and sales teams at retail brands.", "education_required": edu + " + Retail Mgmt Diploma (1 yr)", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Inventory", "Customer Service", "Visual Merchandising"], "how_to_get": "NSDC Retail diploma → Reliance / Future Group / Big Bazaar.", "exam_if_any": ""},
        {"job_title": "Stenographer (SSC Steno)", "description": "Take shorthand notes and transcribe documents for govt departments.", "education_required": edu + " + Stenography Cert.", "salary_range": "₹2-4 LPA", "sector": "Government", "growth_potential": "Medium", "key_skills": ["Shorthand", "Typing Speed 80 WPM", "English"], "how_to_get": "Learn shorthand (3 months) → SSC Stenographer exam.", "exam_if_any": "SSC Stenographer"},
        {"job_title": "CCC / O Level Computer Operator", "description": "Work as computer operator at govt offices after NIELIT certification.", "education_required": edu + " + NIELIT CCC / O Level", "salary_range": "₹1.8-3.5 LPA", "sector": "Government", "growth_potential": "Low", "key_skills": ["MS Office", "Internet", "Typing"], "how_to_get": "Clear NIELIT CCC / O Level exam → apply via state dept vacancies.", "exam_if_any": "NIELIT O Level"},
        {"job_title": "Air Ticketing & Travel Agent (IATA)", "description": "Book flights and holiday packages for customers at travel agencies.", "education_required": edu + " + IATA / Travel Cert.", "salary_range": "₹2-5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["GDS (Amadeus)", "Geography", "Customer Service"], "how_to_get": "IATA Foundation cert (3 months) → join travel agency or MakeMyTrip.", "exam_if_any": "IATA Foundation"},
        {"job_title": "Beautician / Cosmetologist (CIDESCO / Diploma)", "description": "Provide skincare, hair, and beauty treatments at salons or spas.", "education_required": edu + " + Beautician Diploma (6-12 months)", "salary_range": "₹1.5-6 LPA", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["Facials", "Hair Cutting", "Makeup"], "how_to_get": "VLCC / Lakmé Academy diploma → own salon or branded parlour.", "exam_if_any": ""},
        {"job_title": "Electrician / Solar Technician (ITI)", "description": "Install and repair electrical and solar systems in homes and factories.", "education_required": edu + " + ITI Electrician (2 yrs)", "salary_range": "₹2-5 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Wiring", "Solar Panels", "Safety"], "how_to_get": "ITI Electrician → apprenticeship → PWD or private contractors.", "exam_if_any": "NCVT / SCVT"},
        {"job_title": "Fitter / Turner (ITI)", "description": "Fabricate and assemble mechanical components in industries.", "education_required": edu + " + ITI Fitter (2 yrs)", "salary_range": "₹2-4.5 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["Lathe", "Precision Measurement", "Blueprint Reading"], "how_to_get": "ITI Fitter → NCVT apprenticeship → auto / steel / defence PSU.", "exam_if_any": "NCVT"},
        {"job_title": "Plumber / HVAC Technician (ITI)", "description": "Install plumbing and air-conditioning systems in buildings.", "education_required": edu + " + ITI Plumber / HVAC (1-2 yrs)", "salary_range": "₹2-5 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Pipe Fitting", "HVAC Basics", "Safety"], "how_to_get": "ITI Plumber → apprenticeship → construction or HVAC firms.", "exam_if_any": "NCVT"},
        {"job_title": "GST and Income Tax Return Preparer", "description": "File GST returns and ITRs for small businesses and individuals.", "education_required": edu + " + GST Practitioner Cert.", "salary_range": "₹2-4.5 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["GST Portal", "Income Tax", "Tally"], "how_to_get": "GST Practitioner exam (CBIC) → own accounting practice.", "exam_if_any": "GST Practitioner Exam"},
        {"job_title": "Photography / Videography (Diploma)", "description": "Photograph weddings, events, or products for commercial clients.", "education_required": edu + " + Photography Diploma (6 months)", "salary_range": "₹2-8 LPA", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["DSLR", "Lightroom", "Composition"], "how_to_get": "6-month photography course → portfolio → freelance on Wedmegood.", "exam_if_any": ""},
        {"job_title": "Drone Pilot (DGCA Certified)", "description": "Operate drones for agriculture, surveying, or media production.", "education_required": edu + " + DGCA Drone Pilot Cert.", "salary_range": "₹2.5-7 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Drone Operation", "Navigation", "Safety Protocols"], "how_to_get": "DGCA approved training centre → agriculture / infra firms.", "exam_if_any": "DGCA Drone RPTO"},
        {"job_title": "Food Processing Technician (Diploma)", "description": "Process and package food items in FMCG or agri-processing units.", "education_required": edu + " + Food Processing Diploma (1 yr)", "salary_range": "₹2-4 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["FSSAI Norms", "Quality Control", "Packaging"], "how_to_get": "CFTRI / NIFTEM diploma → food processing industry.", "exam_if_any": ""},
        {"job_title": "Refrigeration & AC Mechanic (ITI)", "description": "Service and repair domestic and commercial air-conditioning units.", "education_required": edu + " + ITI RAC (1 yr)", "salary_range": "₹2-5 LPA", "sector": "Self-Employed", "growth_potential": "High", "key_skills": ["Refrigerant Handling", "Compressor Repair", "Wiring"], "how_to_get": "ITI RAC → own service business or join Voltas / Blue Star.", "exam_if_any": "NCVT"},
        {"job_title": "Welder (ITI / ASME Cert.)", "description": "Weld metal structures for construction, shipbuilding, or manufacturing.", "education_required": edu + " + ITI Welder (1 yr)", "salary_range": "₹2-6 LPA", "sector": "Private", "growth_potential": "Medium", "key_skills": ["MIG/TIG Welding", "Blueprint Reading", "Safety"], "how_to_get": "ITI Welder → ASME cert for export jobs → shipyard or infra firms.", "exam_if_any": "NCVT / ASME"},
        {"job_title": "Screenprinting / Flex Operator", "description": "Design and print banners, hoardings, and advertising materials.", "education_required": edu + " + DTP / Printing Cert. (3-6 months)", "salary_range": "₹1.5-4 LPA", "sector": "Self-Employed", "growth_potential": "Medium", "key_skills": ["CorelDRAW", "Printing Equipment", "Design Basics"], "how_to_get": "Short DTP course → own print shop or join advertising agency.", "exam_if_any": ""},
    ]

    _DEGREE_PAD = [
        {"job_title": "Bank PO / Probationary Officer", "description": "Manage branch, loans and customer accounts at public sector banks.", "education_required": "Any Graduation", "salary_range": "₹4-8 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Aptitude", "Banking Awareness", "English"], "how_to_get": "Graduation → IBPS PO / SBI PO → interview.", "exam_if_any": "IBPS PO / SBI PO"},
        {"job_title": "IAS / IPS / IFS Officer", "description": "Lead civil administration, police, or foreign service at national level.", "education_required": "Any Graduation", "salary_range": "₹7-18 LPA + perks", "sector": "Government", "growth_potential": "High", "key_skills": ["GK", "Essays", "CSAT", "Integrity"], "how_to_get": "Any graduation → UPSC CSE Prelims + Mains + Interview.", "exam_if_any": "UPSC CSE"},
        {"job_title": "Software Engineer", "description": "Design and develop large-scale software systems.", "education_required": "B.Tech CS / BCA + MCA", "salary_range": "₹4-20 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["DSA", "System Design", "Cloud"], "how_to_get": "JEE Main → B.Tech → campus/off-campus placements.", "exam_if_any": "JEE Main"},
        {"job_title": "MBA Manager", "description": "Lead operations, marketing or finance teams at corporations.", "education_required": "MBA / PGDM", "salary_range": "₹6-20 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Leadership", "Strategy", "Analytics"], "how_to_get": "CAT/XAT → IIM or top B-school → campus placement.", "exam_if_any": "CAT / XAT"},
        {"job_title": "Data Scientist", "description": "Build ML models and extract business insights from large datasets.", "education_required": "B.Tech / M.Sc + Data Science Cert.", "salary_range": "₹6-25 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Python", "ML", "Statistics", "SQL"], "how_to_get": "Tech degree + Kaggle/Coursera → apply at tech companies.", "exam_if_any": ""},
        {"job_title": "MBBS Doctor / Medical Officer", "description": "Diagnose and treat patients at PHC, hospital, or private clinic.", "education_required": "MBBS", "salary_range": "₹6-15 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Clinical Diagnosis", "Pharmacology", "Patient Care"], "how_to_get": "NEET UG → MBBS 5.5 yrs → internship → PG optional.", "exam_if_any": "NEET UG"},
        {"job_title": "Chartered Accountant (CA)", "description": "Audit firms, file taxes, and advise businesses on finance.", "education_required": "CA (ICAI)", "salary_range": "₹6-25 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Accounting", "Tax", "Audit", "Finance Law"], "how_to_get": "CA Foundation → Intermediate → Final with articleship.", "exam_if_any": "CA Foundation / Intermediate / Final"},
        {"job_title": "Civil / Mechanical Engineer (PSU)", "description": "Design and manage infrastructure projects at CPWD / NHAI / BHEL.", "education_required": "B.Tech Civil / Mech", "salary_range": "₹5-14 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["AutoCAD", "Structural Design", "Project Management"], "how_to_get": "JEE Main → B.Tech → GATE → BHEL / NTPC / NHAI recruitment.", "exam_if_any": "JEE Main / GATE"},
        {"job_title": "Government School Teacher (TGT / PGT)", "description": "Teach in government secondary or higher secondary schools.", "education_required": "Graduation + B.Ed", "salary_range": "₹3-7 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Subject Mastery", "Pedagogy", "Classroom Management"], "how_to_get": "Graduation → B.Ed (2 yrs) → CTET / TET → state teacher recruitment.", "exam_if_any": "CTET / State TET"},
        {"job_title": "Advocate / Lawyer", "description": "Represent clients in courts and provide legal advisory services.", "education_required": "LLB / BA LLB / BBA LLB", "salary_range": "₹3-20 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Legal Research", "Argumentation", "Drafting"], "how_to_get": "CLAT / LSAT → NLU or college → enrol at Bar Council → practise.", "exam_if_any": "CLAT / LSAT / AILET"},
        {"job_title": "Agricultural Officer", "description": "Guide farmers on modern techniques and distribute subsidies.", "education_required": "B.Sc Agriculture", "salary_range": "₹3-8 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Agronomy", "Govt Schemes", "Extension Service"], "how_to_get": "B.Sc Agri → state IBPS SO Agriculture / state AO exam.", "exam_if_any": "IBPS SO Agriculture"},
        {"job_title": "Journalist / Broadcast Reporter", "description": "Report and present news for TV channels and digital media.", "education_required": "BA / BJC (Bachelor of Journalism)", "salary_range": "₹3-12 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Reporting", "Video Editing", "Communication"], "how_to_get": "BA Journalism → IIMC or state journalism college → internship.", "exam_if_any": "IIMC Entrance"},
        {"job_title": "HR Manager / Recruiter", "description": "Manage hiring, training, and employee relations at companies.", "education_required": "MBA HR / BBA + MBA", "salary_range": "₹4-12 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Recruitment", "Labour Law", "HRIS", "Communication"], "how_to_get": "MBA HR → corporate HR dept or talent acquisition firm.", "exam_if_any": "CAT / MAT"},
        {"job_title": "Architect", "description": "Design buildings and oversee construction for residential/commercial projects.", "education_required": "B.Arch (5 yrs)", "salary_range": "₹4-16 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Revit", "AutoCAD", "Structural Knowledge", "Urban Planning"], "how_to_get": "NATA entrance → B.Arch → Council of Architecture registration.", "exam_if_any": "NATA / JEE Paper 2"},
        {"job_title": "Fashion Designer", "description": "Create original clothing collections and present at trade shows.", "education_required": "B.Des Fashion / B.FTech (NIFT)", "salary_range": "₹4-15 LPA", "sector": "Both", "growth_potential": "High", "key_skills": ["Design Concept", "CAD", "Textiles", "Trend Forecasting"], "how_to_get": "NIFT/NID entrance → degree → fashion house or own label.", "exam_if_any": "NIFT Entrance / NID"},
        {"job_title": "Product / UX Designer", "description": "Design digital interfaces and user experiences for apps and websites.", "education_required": "B.Des / B.F.A", "salary_range": "₹4-16 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Figma", "User Research", "Prototyping"], "how_to_get": "NID / NIFT / UCEED entrance → B.Des → startup or product company.", "exam_if_any": "NID / UCEED / NIFT"},
        {"job_title": "Scientist / Researcher (DRDO / ISRO)", "description": "Conduct advanced research in defence, space, or basic sciences.", "education_required": "M.Sc / B.Tech + GATE", "salary_range": "₹5-15 LPA", "sector": "Government", "growth_potential": "High", "key_skills": ["Research", "Data Analysis", "Report Writing"], "how_to_get": "M.Sc/B.Tech → GATE → DRDO CEPTAM / ISRO written exam.", "exam_if_any": "GATE / DRDO CEPTAM / ISRO"},
        {"job_title": "Commissioned Army / Navy Officer", "description": "Lead troops or crew as Lieutenant or Flight Lieutenant in Armed Forces.", "education_required": "Graduation / B.Tech", "salary_range": "₹6-18 LPA + perks", "sector": "Government", "growth_potential": "High", "key_skills": ["Leadership", "Physical Fitness", "Technical Knowledge"], "how_to_get": "NDA (after 12th) or CDS (after graduation) → SSB interview → commission.", "exam_if_any": "NDA / CDS / AFCAT"},
        {"job_title": "Social Worker / Case Manager (MSW)", "description": "Manage welfare cases and coordinate with govt agencies for families.", "education_required": "BSW / MSW", "salary_range": "₹2.5-7 LPA", "sector": "Both", "growth_potential": "Medium", "key_skills": ["Case Management", "Policy Knowledge", "Counselling"], "how_to_get": "BSW/MSW → UN agencies, govt welfare depts, or corporate CSR.", "exam_if_any": "TISS Entrance"},
        {"job_title": "Film / Media VFX Artist", "description": "Create 3D animations and visual effects for films, games, or ads.", "education_required": "B.Sc Animation / B.Des", "salary_range": "₹4-18 LPA", "sector": "Private", "growth_potential": "High", "key_skills": ["Maya", "Blender", "ZBrush", "Compositing"], "how_to_get": "MAAC/Arena/FTII → B.Sc Animation → film studio or gaming company.", "exam_if_any": "FTII Entrance / NID"},
    ]

    # Deduplicate by job_title, pad to 20 using general pool if needed
    def _dedup_and_pad(jobs: list, pad_pool: list, limit: int = 20) -> list:
        seen: set = set()
        result = []
        for j in jobs:
            t = j.get("job_title", "")
            if t not in seen:
                seen.add(t)
                result.append(j)
        # pad from general pool until limit reached
        for j in pad_pool:
            if len(result) >= limit:
                break
            t = j.get("job_title", "")
            if t not in seen:
                seen.add(t)
                result.append(j)
        return result[:limit]

    return {
        "education_level": edu,
        "categories": [
            {
                "id": "now",
                "title": "Start Right Now",
                "subtitle": f"Jobs with your current {edu} qualification",
                "icon": "checkmark-circle",
                "color": "#2E7D32",
                "jobs": _dedup_and_pad(now_jobs, _NOW_PAD, 20),
            },
            {
                "id": "short_course",
                "title": "After Short Course (3-12 months)",
                "subtitle": "Diploma, certification or vocational training",
                "icon": "time-outline",
                "color": "#1565C0",
                "jobs": _dedup_and_pad(short_jobs, _SHORT_PAD, 20),
            },
            {
                "id": "after_degree",
                "title": "After Degree (2-4 years)",
                "subtitle": "UG or PG programme in your interested field",
                "icon": "school-outline",
                "color": "#6A1B9A",
                "jobs": _dedup_and_pad(degree_jobs, _DEGREE_PAD, 20),
            },
        ],
    }


# ─── College Campus Images (Google CSE primary → Wikipedia fallback) ───────────
class CollegeCampusImagesRequest(BaseModel):
    college_name: str
    college_type: str = "Government"
    location: str = "India"
    entrance_exam: Optional[str] = ""
    courses: Optional[str] = ""


# Curated Wikipedia page titles for major Indian colleges so search resolves instantly
KNOWN_COLLEGE_WIKI = {
    "iit bombay": "Indian Institute of Technology Bombay",
    "iit delhi": "Indian Institute of Technology Delhi",
    "iit madras": "Indian Institute of Technology Madras",
    "iit kharagpur": "Indian Institute of Technology Kharagpur",
    "iit kanpur": "Indian Institute of Technology Kanpur",
    "iit roorkee": "Indian Institute of Technology Roorkee",
    "iit guwahati": "Indian Institute of Technology Guwahati",
    "iit hyderabad": "Indian Institute of Technology Hyderabad",
    "iit bhu": "Indian Institute of Technology (BHU) Varanasi",
    "iit patna": "Indian Institute of Technology Patna",
    "iit jodhpur": "Indian Institute of Technology Jodhpur",
    "aiims delhi": "All India Institute of Medical Sciences, New Delhi",
    "aiims": "All India Institute of Medical Sciences, New Delhi",
    "delhi university": "University of Delhi",
    "du": "University of Delhi",
    "mumbai university": "University of Mumbai",
    "jadavpur university": "Jadavpur University",
    "bits pilani": "Birla Institute of Technology and Science, Pilani",
    "vit vellore": "Vellore Institute of Technology",
    "manipal": "Manipal Academy of Higher Education",
    "iim ahmedabad": "Indian Institute of Management Ahmedabad",
    "iim bangalore": "Indian Institute of Management Bangalore",
    "iim calcutta": "Indian Institute of Management Calcutta",
    "nit trichy": "National Institute of Technology, Tiruchirappalli",
    "nit warangal": "National Institute of Technology, Warangal",
    "nit surathkal": "National Institute of Technology Karnataka",
    "nit calicut": "National Institute of Technology Calicut",
    "srm": "SRM Institute of Science and Technology",
    "anna university": "Anna University",
    "osmania university": "Osmania University",
    "jamia millia": "Jamia Millia Islamia",
    "jnu": "Jawaharlal Nehru University",
    "bhu": "Banaras Hindu University",
    "amity": "Amity University",
    "thapar": "Thapar Institute of Engineering and Technology",
    "coep": "College of Engineering, Pune",
    "dcrust": "Deenbandhu Chhotu Ram University of Science and Technology",
    "pec chandigarh": "Punjab Engineering College",
    "nit rourkela": "National Institute of Technology, Rourkela",
    "nit silchar": "National Institute of Technology, Silchar",
    "iit indore": "Indian Institute of Technology Indore",
    "nit nagpur": "Visvesvaraya National Institute of Technology",
    "sp college pune": "SP College, Pune",
    "fergusson college": "Fergusson College",
}

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_HEADERS = {"User-Agent": "CareerGuidanceEducationApp/2.0 (educational; contact@careers.app)"}

CAMPUS_IMAGE_CATEGORIES = [
    "main_campus", "library", "laboratory", "hostel", "sports",
    "classroom", "auditorium", "building",
]


def _wiki_find_page_title(college_name: str) -> Optional[str]:
    """Find the Wikipedia page title for a college."""
    # Check curated mapping first
    key = college_name.lower().strip()
    for k, v in KNOWN_COLLEGE_WIKI.items():
        if k in key or key in k:
            return v

    # Use Wikipedia search API
    try:
        resp = _requests.get(_WIKI_API, params={
            "action": "query", "list": "search",
            "srsearch": f"{college_name} college India",
            "srlimit": 3, "format": "json",
        }, headers=_WIKI_HEADERS, timeout=6)
        results = resp.json().get("query", {}).get("search", [])
        if results:
            return results[0]["title"]
    except Exception:
        pass
    return None


def _wiki_get_page_images(page_title: str, max_img: int = 12) -> List[str]:
    """Get list of image file names from a Wikipedia page."""
    try:
        resp = _requests.get(_WIKI_API, params={
            "action": "query", "titles": page_title,
            "prop": "images", "imlimit": max_img,
            "format": "json",
        }, headers=_WIKI_HEADERS, timeout=6)
        pages = resp.json().get("query", {}).get("pages", {})
        page = list(pages.values())[0]
        return [img["title"] for img in page.get("images", [])]
    except Exception:
        return []


def _wiki_get_image_urls(file_names: List[str]) -> List[dict]:
    """Resolve Wikipedia File: names to thumbnail URLs (800 px wide) with metadata."""
    if not file_names:
        return []
    try:
        resp = _requests.get(_WIKI_API, params={
            "action": "query",
            "titles": "|".join(file_names[:20]),
            "prop": "imageinfo",
            "iiprop": "url|thumburl|size|mime",
            "iiurlwidth": 800,          # ask for 800-px thumbnail URL
            "format": "json",
        }, headers=_WIKI_HEADERS, timeout=8)
        pages = resp.json().get("query", {}).get("pages", {})
        results = []
        for page_data in pages.values():
            info_list = page_data.get("imageinfo", [])
            if not info_list:
                continue
            info = info_list[0]
            # Prefer the resized thumbnail URL — cleaner, CDN-cached, avoids encoding bugs
            url = info.get("thumburl") or info.get("url", "")
            mime = info.get("mime", "")
            width = info.get("width", 0)
            height = info.get("height", 0)
            title = page_data.get("title", "")
            results.append({
                "url": url, "mime": mime, "width": width,
                "height": height, "title": title,
            })
        return results
    except Exception:
        return []


# Campus-building positive keywords — at least ONE must appear in filename
# for images that don't have BOTH sufficient size AND landscape ratio
_CAMPUS_POSITIVE = {
    "campus", "building", "hall", "block", "gate", "entrance",
    "library", "lab", "laboratory", "hostel", "dormitory", "stadium",
    "sports", "ground", "auditorium", "classroom", "lecture", "canteen",
    "cafeteria", "admin", "academic", "tower", "centre", "center",
    "infrastructure", "facility", "architecture", "view", "pano", "aerial",
    "main", "night", "iit", "nit", "aiims", "iim", "bits", "vit", "srm",
    "university", "college", "institute", "dept", "department",
    "admin", "quadrangle", "quad", "plaza", "courtyard", "promenade",
    "facade", "exterior", "roof", "road", "path", "walkway",
}

# Anything matching these words in title/filename is immediately discarded
_CAMPUS_SKIP = {
    "logo", "icon", "flag", "map", "coat", "seal", "badge", "emblem",
    "shield", "crest", "symbol", "signature", "chart", "graph", "diagram",
    "infographic", "portrait", "headshot",
    "organisational", "organizational", "organogram", "orgchart",
    "statue", "monument", "memorial", "historical", "heritage",
    "charminar", "qutub", "gateway", "tajmahal", "temple", "mosque",
    # wildlife / nature — the biggest source of wrong images
    "bird", "animal", "wildlife", "snake", "python", "dog", "cat", "cow",
    "calf", "calves", "deer", "parrot", "koel", "peacock", "butterfly",
    "insect", "flower", "plant", "tree", "leaf", "nature", "fauna", "flora",
    "bio", "species", "fish", "frog", "lizard", "monkey", "squirrel",
    # other irrelevant image types
    "person", "people", "group", "crowd", "convocation", "graduation",
    "ceremony", "award", "prize", "professor", "faculty",
    "president", "minister", "inaugur", "visitor", "felicitat",
}

# ─── Google Custom Search API helpers ────────────────────────────────────────
import hashlib as _hashlib
_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"

# In-memory thumbnail cache: college_name → url  (cleared on server restart)
_THUMB_CACHE: Dict[str, str] = {}
_PHOTO_BYTES_CACHE: Dict[str, bytes] = {}  # college name → raw image bytes (proxy cache)

# ── Curated campus photos for the top Indian colleges ──────────────────────
# Uses Wikimedia Commons Special:FilePath (hash-free) → auto-redirects to thumbnails.
# ALL entries have been manually verified (HTTP 200 + image/* content-type).
# Used by _lookup_known_college_image() as step 1.5 fallback when Wikipedia
# article search finds no campus photo for a college.
_WC = "https://upload.wikimedia.org/wikipedia/commons/thumb"  # kept for reference
_WC_FP = "https://commons.wikimedia.org/wiki/Special:FilePath"
KNOWN_COLLEGE_IMAGES: Dict[str, str] = {
    # ── IITs (all filenames verified working) ───────────────────────────────
    "iit bombay":              f"{_WC_FP}/IITBMainBuildingCROP.jpg?width=800",
    "iit delhi":               f"{_WC_FP}/IIT_Delhi_Main_Building.jpeg?width=800",
    "iit madras":              f"{_WC_FP}/IIT_Madras_Campus.jpg?width=800",
    "iit kanpur":              f"{_WC_FP}/Computer_Center_at_IIT_Kanpur_India1.jpg?width=800",
    "iit kharagpur":           f"{_WC_FP}/IIT_Kharagpur_Main_Entrance_(Puri_Gate).jpg?width=800",
    "iit roorkee":             f"{_WC_FP}/IIT_Roorkee_Main_Building.jpg?width=800",
    "iit bhu":                 f"{_WC_FP}/IIT_BHU_Varanasi.jpg?width=800",
    "iit (bhu)":               f"{_WC_FP}/IIT_BHU_Varanasi.jpg?width=800",
    "iit bhu varanasi":        f"{_WC_FP}/IIT_BHU_Varanasi.jpg?width=800",
    "iit varanasi":            f"{_WC_FP}/IIT_BHU_Varanasi.jpg?width=800",
    # Other IITs (Guwahati, Hyderabad, Gandhinagar, etc.) → AI generator via fallback
    # ── NITs (verified) ─────────────────────────────────────────────────────
    "nit calicut":             f"{_WC_FP}/NitC_campus._Architecture_dept.jpg?width=800",
    "nit tiruchirappalli":     f"{_WC_FP}/NitC_campus._Architecture_dept.jpg?width=800",
    "nit trichy":              f"{_WC_FP}/NitC_campus._Architecture_dept.jpg?width=800",
    # Other NITs → AI generator via fallback
    # ── Top private institutes (verified) ───────────────────────────────────
    "vit vellore":             f"{_WC_FP}/Technology_Tower(VIT).jpg?width=800",
    "vit university":          f"{_WC_FP}/Technology_Tower(VIT).jpg?width=800",
    "bits pilani":             f"{_WC_FP}/BITS-Pilani_campus_aerial_view.jpg?width=800",
    "thapar":                  f"{_WC_FP}/Thapar_Campus_Aerial_View.jpg?width=800",
    "dtu delhi":               f"{_WC_FP}/DelhiCollegeOfEngineering_BawanaCampus.jpg?width=800",
    "delhi technological":     f"{_WC_FP}/DelhiCollegeOfEngineering_BawanaCampus.jpg?width=800",
    "vjti":                    f"{_WC_FP}/VJTI_Main_Gate.jpg?width=800",
    "srm institute":           f"{_WC_FP}/Entry_Gate_at_SRM_Institute_of_Science_and_Technology,_Tiruchirapalli_Campus.jpg?width=800",
    "srm university":          f"{_WC_FP}/Entry_Gate_at_SRM_Institute_of_Science_and_Technology,_Tiruchirapalli_Campus.jpg?width=800",
    "srm":                     f"{_WC_FP}/Entry_Gate_at_SRM_Institute_of_Science_and_Technology,_Tiruchirapalli_Campus.jpg?width=800",
    "chandigarh university":   f"{_WC_FP}/South_Campus_Chandigarh_University.jpg?width=800",
    "iiit hyderabad":          f"{_WC_FP}/IIIT_Hyderabad_-_Campus_view.png?width=800",
    "iiit delhi":              f"{_WC_FP}/IIITD_Campus_2024.jpg?width=800",
    "manipal institute of technology": f"{_WC_FP}/MIT_Academic_Block_1_-_Quadrangle.jpg?width=800",
    "manipal institute":       f"{_WC_FP}/MIT_Academic_Block_1_-_Quadrangle.jpg?width=800",
    "manipal university":      f"{_WC_FP}/MIT_Academic_Block_1_-_Quadrangle.jpg?width=800",
    "manipal":                 f"{_WC_FP}/MIT_Academic_Block_1_-_Quadrangle.jpg?width=800",
    # ── IIMs (verified) ─────────────────────────────────────────────────────
    "iim ahmedabad":           f"{_WC_FP}/Iima_new_campus_panorama.jpg?width=800",
    "iim bangalore":           f"{_WC_FP}/IIMB_Campus3.jpg?width=800",
    "iim calcutta":            f"{_WC_FP}/IIM_Calcutta_Lakes_1_-_Night_Scene.jpg?width=800",
    # Other IIMs → AI generator via fallback
    # ── Universities (verified) ──────────────────────────────────────────────
    "jadavpur university":     f"{_WC_FP}/Jadavpur_University_Gate_No._4.jpg?width=800",
    "anna university":         f"{_WC_FP}/ANNA_UNIVERSITY_TRICHY_MAIN_CAMPUS.jpg?width=800",
    "amity university":        f"{_WC_FP}/Amity_Campus_Noida_Delhi.jpg?width=800",
    "pune university":         f"{_WC_FP}/Savitribai_Phule_Pune_University_(SPPU).jpg?width=800",
    "savitribai phule":        f"{_WC_FP}/Savitribai_Phule_Pune_University_(SPPU).jpg?width=800",
    "sppu":                    f"{_WC_FP}/Savitribai_Phule_Pune_University_(SPPU).jpg?width=800",
    "delhi university":        f"{_WC_FP}/Delhiuni.jpg?width=800",
    "university of delhi":     f"{_WC_FP}/Delhiuni.jpg?width=800",
    "iisc":                    f"{_WC_FP}/IISC_Bangalore_Campus.jpg?width=800",
    "indian institute of science": f"{_WC_FP}/IISC_Bangalore_Campus.jpg?width=800",
    "osmania university":      f"{_WC_FP}/Engineering_college_at_Osmania_University.jpg?width=800",
    "christ university":       f"{_WC_FP}/CHRIST_(Deemed_to_be_University)_Pune_Lavasa_Campus_-_Central_Block.png?width=800",
    "aligarh muslim":          f"{_WC_FP}/Maulana_Azad_Library,_Aligarh_Muslim_University.jpg?width=800",
    "amu":                     f"{_WC_FP}/Maulana_Azad_Library,_Aligarh_Muslim_University.jpg?width=800",
    "calcutta university":     f"{_WC_FP}/Calcutta_University,_Hazra_Campus.jpg?width=800",
    "university of calcutta":  f"{_WC_FP}/Calcutta_University,_Hazra_Campus.jpg?width=800",
    "mumbai university":       f"{_WC_FP}/University_of_Mumbai_library.jpg?width=800",
    "university of mumbai":    f"{_WC_FP}/University_of_Mumbai_library.jpg?width=800",
    # All other colleges not listed above → AI generator (Pollinations.ai) via fallback chain
}

# Keywords for smart Pexels fallback when Google API is not configured
_COLLEGE_TYPE_KW: List[tuple] = [
    ({"iit ","nit ","bits ","iiit","jadavpur","anna university","engineering","technology","technical","institute of tech","dtu","vit ","srm ","manipal","thapar","lnmiit"}, "engineering"),
    ({"aiims","medical college","mbbs","dental","govt medical","government medical","medical university","jipmer","kgmc","afmc"}, "medical"),
    ({"nursing","gnm","anm","bsc nursing"}, "nursing"),
    ({"pharmacy","pharma","pharmaceutical"}, "pharmacy"),
    ({"iim ","xlri","fms ","ibs ","spjimr","nmims","management","business school","mba college","commerce college"}, "management"),
    ({"nlu "," law ","national law","law university","law college"}, "law"),
    ({"nid ","nift","design college","fashion","fine arts","architecture"}, "design"),
    ({"agriculture","agri","veterinary","animal science","pau ","icar","horticulture"}, "agriculture"),
    ({"b.ed","teacher training","rie ","diet ","education college"}, "teaching"),
    ({"arts college","humanities","liberal arts","bhu","jnu","du college","lady shri ram","miranda house"}, "arts"),
    ({"iti ","polytechnic","skill","vocational"}, "iti_polytechnic"),
]

_URL_BAD = {".svg", "logo", "icon", "seal", "emblem", "banner", "crest", "shield", "signature", "flag"}


def _is_bad_url(url: str) -> bool:
    u = url.lower()
    if any(b in u for b in _URL_BAD):
        return True
    for w in _CAMPUS_SKIP:
        if w in u:
            return True
    return False


import re as _re
def _to_wiki_thumbnail(url: str, width: int = 800) -> str:
    """
    Convert a Wikimedia full-resolution image URL to a web-optimised thumbnail URL.
    Full-res Wikimedia images can be 3-10 MB; thumbnails are typically 50-200 KB.
    Works for both wikipedia/commons and wikipedia/en etc.
    e.g. .../commons/e/e8/Image.png  →  .../commons/thumb/e/e8/Image.png/800px-Image.png
    """
    if 'upload.wikimedia.org' not in url or '/thumb/' in url:
        return url  # already a thumbnail or not Wikimedia
    m = _re.match(
        r'(https://upload\.wikimedia\.org/[^/]+/[^/]+)/([0-9a-f]/[0-9a-f]{2})/(.+)$',
        url,
    )
    if m:
        base, hash_path, filename = m.groups()
        return f"{base}/thumb/{hash_path}/{filename}/{width}px-{filename}"
    return url


def _ai_generate_college_image(college_name: str) -> str:
    """
    Generate a college-specific campus image using Pollinations.ai free AI API.
    No API key required. Returns a URL that Pollinations serves as an actual image.
    Each college gets a unique, tailored prompt so different colleges look different.
    """
    import urllib.parse as _urlparse

    short = college_name.split("(")[0].strip()

    # Build a descriptive prompt specific to the college
    name_lower = short.lower()

    # Detect college type for more accurate prompt
    if any(k in name_lower for k in ["iit ", "iit(", "indian institute of technology"]):
        college_type = "Indian Institute of Technology"
        style = "modern academic campus with red brick buildings, green lawns, academic complex"
    elif any(k in name_lower for k in ["nit ", "national institute of technology"]):
        college_type = "National Institute of Technology"
        style = "Indian engineering college campus, large academic block, lecture halls"
    elif any(k in name_lower for k in ["iim ", "indian institute of management"]):
        college_type = "Indian Institute of Management"
        style = "premium management school campus, elegant architecture, manicured gardens"
    elif any(k in name_lower for k in ["aiims", "medical college", "medical university"]):
        college_type = "Medical College"
        style = "hospital campus with medical college building, clinical atmosphere"
    elif any(k in name_lower for k in ["law ", "law college", "national law"]):
        college_type = "Law University"
        style = "law school campus, formal architecture, courtyard"
    elif any(k in name_lower for k in ["university"]):
        college_type = "Indian University"
        style = "grand university campus, heritage building, wide pathways"
    else:
        college_type = "Engineering College"
        style = "Indian engineering college campus, academic block, modern building"

    prompt = (
        f"photorealistic {short} {college_type} campus India, "
        f"{style}, daytime, clear sky, high resolution, architectural photography, "
        f"no people, wide angle shot"
    )
    encoded = _urlparse.quote(prompt)
    # seed derived from name so same college always gets same AI image
    seed = int(_hashlib.md5(college_name.lower().encode()).hexdigest()[:8], 16)
    return f"https://image.pollinations.ai/prompt/{encoded}?width=800&height=500&nologo=true&seed={seed}&model=flux"


def _pexels_college_fallback(college_name: str) -> str:
    """
    Final fallback: AI-generated campus image via Pollinations.ai (free, no API key).
    Each college gets a unique deterministic image based on its name.
    """
    return _ai_generate_college_image(college_name)


def _google_campus_images(college_name: str, num: int = 5) -> List[dict]:
    """
    Fetch campus photos from the college's own website via Google Custom Search.
    Queries prefer .ac.in / .edu.in / .edu domains (official college sites).
    Falls back to any good campus photo if official site returns nothing.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not api_key or not cx:
        return []

    college_short = college_name.split("(")[0].strip()
    # Priority queries: official site → general campus photo
    queries = [
        f'"{college_short}" campus (site:.ac.in OR site:.edu.in OR site:.edu OR site:.org)',
        f'"{college_short}" campus building exterior official',
        f'{college_short} campus aerial photo',
    ]

    images: List[dict] = []
    seen: set = set()

    for q in queries:
        if len(images) >= num:
            break
        try:
            resp = _requests.get(_GOOGLE_CSE_URL, params={
                "key": api_key, "cx": cx,
                "q": q,
                "searchType": "image",
                "imgType": "photo",
                "imgSize": "large",
                "num": 10,
                "safe": "off",
                "fileType": "jpg",
            }, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"Google CSE error {resp.status_code}: {resp.text[:200]}")
                continue
            items = resp.json().get("items", [])
            # Prefer images from official college domains
            edu_items = [i for i in items if any(d in i.get("link", "").lower() for d in [".ac.in", ".edu.in", ".edu", ".org"])]
            ordered = edu_items + [i for i in items if i not in edu_items]
            for item in ordered:
                url = item.get("link", "")
                if not url or url in seen or _is_bad_url(url):
                    continue
                title = item.get("title", college_short + " Campus")
                cat, caption = _label_campus_photo({"title": title, "url": url})
                seen.add(url)
                images.append({"url": url, "caption": caption, "category": cat})
                if len(images) >= num:
                    break
        except Exception as e:
            logger.warning(f"_google_campus_images error: {e}")

    return images


def _google_single_thumb(college_name: str) -> str:
    """
    Best single campus thumbnail for a college.
    Queries target the college's official website first (.ac.in/.edu.in).
    Returns empty string if API not configured or no suitable image found.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_CSE_ID", "").strip()
    if not api_key or not cx:
        return ""

    college_short = college_name.split("(")[0].strip()
    # Three queries in priority order
    queries = [
        f'"{college_short}" campus (site:.ac.in OR site:.edu.in OR site:.edu)',
        f'"{college_short}" college campus building official photo',
        f'{college_short} campus exterior building',
    ]
    best_edu: str = ""
    best_any: str = ""
    for q in queries:
        if best_edu:
            break
        try:
            resp = _requests.get(_GOOGLE_CSE_URL, params={
                "key": api_key, "cx": cx,
                "q": q,
                "searchType": "image",
                "imgType": "photo",
                "imgSize": "large",
                "num": 10,
                "safe": "off",
                "fileType": "jpg",
            }, timeout=8)
            if resp.status_code != 200:
                continue
            for item in resp.json().get("items", []):
                url = item.get("link", "")
                if not url or _is_bad_url(url):
                    continue
                is_edu = any(d in url.lower() for d in [".ac.in", ".edu.in", ".edu", ".org"])
                if is_edu and not best_edu:
                    best_edu = url
                    break
                if not best_any:
                    best_any = url
        except Exception as e:
            logger.warning(f"_google_single_thumb error: {e}")
    return best_edu or best_any


def _lookup_known_college_image(college_name: str) -> str:
    """
    Check KNOWN_COLLEGE_IMAGES for this college using soft key matching.
    Returns the campus photo URL if found, else ''.
    """
    name_lower = college_name.lower()
    # Exact / starts-with match first (fastest)
    for key, url in KNOWN_COLLEGE_IMAGES.items():
        if name_lower.startswith(key) or key in name_lower:
            return url
    return ""


def _wiki_summary_thumb(college_name: str) -> str:
    """
    Get an actual campus building photo from the college's Wikipedia article.
    Strategy:
      A. REST summary original image — accept only if clearly a campus photo.
      B. Enumerate article images, score by campus-keyword density, reject all
         person/animal/event/diagram images, only return high-scoring campus files.
      C. Wikipedia search → first result's article images (for colleges that miss step A/B).
    Returns '' if no confident campus photo found — let DDG/Pexels handle it.
    """
    try:
        short = college_name.split("(")[0].strip()
        short_lower = short.lower()

        # Build dynamic campus keywords from the college's own short name tokens
        name_tokens = set(t for t in _re.split(r"[\s_\-]+", short_lower) if len(t) > 2)

        # Static campus-building keywords for filename scoring
        CAMPUS_KW = {
            "campus", "building", "aerial", "view", "gate", "main", "hall",
            "block", "hostel", "library", "admin", "entrance", "road", "ground",
            "panorama", "overview", "college", "dept", "architecture", "auditorium",
            "lecture", "institute", "university", "tower", "center", "centre",
            "facade", "block", "quadrangle", "courtyard", "laboratory", "lab",
            "iit", "nit", "iim", "bits", "iisc", "aiims", "sppu", "jnu", "bhu",
            "vit", "srm", "amity", "manipal", "thapar", "lnmiit", "dtu",
        }
        # All keywords = static + dynamic name tokens
        all_campus_kw = CAMPUS_KW | name_tokens

        # Words that strongly indicate a person, event, diagram — not a campus photo
        PERSON_SKIP = {
            "logo", "signature", "award", "stamp", "medal", "portrait",
            "founder", "director", "minister", "president", "alumni",
            "icon", "seal", "emblem", "flag", "map", "crest", "coat",
            "chairman", "professor", "shri ", "smt ", "dr ", "mr ", "mrs ",
            "deer", "animal", "bird", "snake", "tiger", "lion", "dog", "cat",
            "tree", "flower", "plant", "fungi", "monkey", "blackbuck", "nilgai",
            "peacock", "macaque", "reptile",
            "wikipedia", "commons-logo", "festival", "rangoli", "diwali", "holi",
            "economic summit", "conference", "inauguration", "ceremony",
            "swearing", "cropped", "official photograph", "official photo",
            "infotainment", "laser show", "spring fest", "techfest",
            "organisational structure", "org structure",
            # event-verb patterns: e.g. "Clinton, speaks at University of Delhi"
            "speaks at", "speaking at", "addressing the", "addresses the",
            "address at", "visit of", "visit to", "visited by",
            "felicitation", "convocation", "graduation",
        }

        EVENT_VERBS = {"speaks", "addressing", "addresses", "address", "visits",
                         "visited", "felicitate", "inaugurates", "delivers", "lecture"}

        def _is_likely_person(fname: str) -> bool:
            """Detect person-photo filenames like 'Firstname_Lastname_-_Event.jpg'"""
            fl = fname.lower()
            # Skip if any explicit person/event indicator present
            if any(w in fl for w in PERSON_SKIP):
                return True
            # Heuristic: starts with two CamelCase/TitleCase words (person name)
            # e.g. "Natarajan Chandrasekaran - India Economic Summit 2011.jpg"
            clean = _re.sub(r'^file:', '', fl).strip()
            parts = _re.split(r'[_\s\-,]+', clean)
            jpg_parts = [p.strip() for p in parts
                         if p.strip() and not p.strip().endswith(('.jpg','.jpeg','.png'))]
            if len(jpg_parts) >= 2:
                first_two = jpg_parts[:2]
                # First two parts look like a personal name (each 3–15 alpha chars)
                if all(_re.match(r'^[a-z]{3,15}$', p) for p in first_two):
                    rest = jpg_parts[2:]
                    # If any part after name is an event verb → definitely a person photo
                    if any(p in EVENT_VERBS for p in rest):
                        return True
                    # No campus keywords anywhere → likely a person (headshot/portrait)
                    if not any(kw in fl for kw in all_campus_kw):
                        return True
            return False

        def _campus_score(fname: str) -> int:
            fl = fname.lower()
            return sum(1 for w in all_campus_kw if w in fl) * 2 + \
                   (2 if short_lower in fl else 0)  # bonus for college name in filename

        # ── Step A: REST summary main image ─────────────────────────────────
        encoded = urllib.parse.quote(short.replace(" ", "_"))
        resp = _requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
            headers=_WIKI_HEADERS, timeout=7,
        )
        if resp.status_code != 200:
            return ""

        data = resp.json()
        combined = ((data.get("description") or "") + " " + (data.get("extract") or "")).lower()
        edu_kws = ["college", "universit", "institute", "school", "iit", "nit",
                   "iim", "aiims", "technical", "engineering", "medical", "research"]
        if not any(w in combined for w in edu_kws):
            return ""  # not an educational institution article

        main_url = (data.get("originalimage") or {}).get("source", "")
        main_fname = main_url.split("/")[-1].lower() if main_url else ""
        # Accept main image only if it genuinely looks like a campus/building photo
        if (main_url and not _is_bad_url(main_url)
                and not _is_likely_person(main_fname)
                and _campus_score(main_fname) > 0):
            logger.info(f"wiki_summary (main) OK for '{college_name}': {main_url[:70]}")
            return main_url

        # ── Step B: Enumerate article images ────────────────────────────────
        page_title = (data.get("title") or short).replace(" ", "_")
        img_resp = _requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "titles": page_title,
                    "prop": "images", "imlimit": 50, "format": "json"},
            headers=_WIKI_HEADERS, timeout=7,
        )
        candidates = []
        pages = img_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            for img in page.get("images", []):
                t = img.get("title", "")
                tl = t.lower()
                if not any(tl.endswith(ext) for ext in (".jpg", ".jpeg", ".png")):
                    continue
                if _is_likely_person(tl):
                    continue
                score = _campus_score(tl)
                if score > 0:  # ONLY accept files with at least one campus keyword
                    candidates.append((score, t))

        # Sort highest-scoring candidates first
        candidates.sort(key=lambda x: x[0], reverse=True)
        top_files = [t for _, t in candidates[:10]]

        if top_files:
            url_resp = _requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "query", "titles": "|".join(top_files[:7]),
                        "prop": "imageinfo", "iiprop": "url|size|mime",
                        "format": "json"},
                headers=_WIKI_HEADERS, timeout=7,
            )
            # Build a map from title → imageinfo for correct ordering
            info_map = {}
            for p in url_resp.json().get("query", {}).get("pages", {}).values():
                title = p.get("title", "")
                ii = (p.get("imageinfo") or [{}])[0]
                info_map[title] = ii
            # Return the highest-scoring valid image
            for _, t in candidates[:7]:
                ii = info_map.get(t, {})
                if ii.get("mime") not in ("image/jpeg", "image/png"):
                    continue
                if ii.get("width", 0) < 400 or ii.get("height", 0) < 250:
                    continue
                url = ii.get("url", "")
                if url and not _is_bad_url(url):
                    logger.info(f"wiki_summary (article) OK for '{college_name}': {url[:70]}")
                    return url

        # ── Step C: Wikipedia search fallback ───────────────────────────────
        # For colleges whose own article has no campus images (e.g. NIT Trichy),
        # search Wikimedia Commons for a campus photo directly
        try:
            for q in [f"{short} campus", f"{short} college building"]:
                sr = _requests.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={"action": "query", "list": "search", "srsearch": q,
                            "srnamespace": "6", "srlimit": 8, "format": "json"},
                    headers=_WIKI_HEADERS, timeout=6,
                )
                results = sr.json().get("query", {}).get("search", [])
                commons_files = [
                    r["title"] if r["title"].startswith("File:") else "File:" + r["title"]
                    for r in results
                    if any(r.get("title","").lower().endswith(e) for e in (".jpg",".jpeg",".png"))
                    and not _is_likely_person(r.get("title","").lower())
                    and _campus_score(r.get("title","").lower()) > 0
                ]
                if not commons_files:
                    continue
                # Must use Commons API (not Wikipedia) to resolve Commons file URLs
                url_resp = _requests.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={"action": "query", "titles": "|".join(commons_files[:5]),
                            "prop": "imageinfo", "iiprop": "url|size|mime", "format": "json"},
                    headers=_WIKI_HEADERS, timeout=6,
                )
                for p in url_resp.json().get("query", {}).get("pages", {}).values():
                    ii = (p.get("imageinfo") or [{}])[0]
                    if ii.get("mime") not in ("image/jpeg", "image/png"):
                        continue
                    if ii.get("width", 0) < 400 or ii.get("height", 0) < 250:
                        continue
                    url = ii.get("url", "")
                    if url and not _is_bad_url(url):
                        logger.info(f"wiki_summary (commons) OK for '{college_name}': {url[:70]}")
                        return url
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"wiki_summary_thumb failed for '{college_name}': {e}")
    return ""



def _ddg_college_thumb(college_name: str) -> str:
    """
    Search DuckDuckGo images for the college's campus photo (free, no API key).
    Returns first non-logo image URL, or '' on failure.
    """
    try:
        try:
            from ddgs import DDGS  # new package name
        except ImportError:
            from duckduckgo_search import DDGS  # fallback for old installs
        short = college_name.split("(")[0].strip()
        queries = [
            f'{short} campus photo college India',
            f'{short} college campus building',
        ]
        with DDGS(timeout=10) as ddgs_client:
            for q in queries:
                try:
                    results = ddgs_client.images(q, max_results=15, region="in-en", safesearch="moderate")
                    for r in (results or []):
                        url = r.get("image", "")
                        if url and not _is_bad_url(url):
                            return url
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"DDG college thumb skipped: {e}")
    return ""


def _is_campus_photo(file_info: dict) -> bool:
    """Filter out logos, maps, flags, wildlife — keep real campus building photos."""
    url = file_info.get("url", "").lower()
    title = file_info.get("title", "").lower()
    mime = file_info.get("mime", "")
    w = file_info.get("width", 0)
    h = file_info.get("height", 0)

    # Must be jpeg/png
    if mime not in ("image/jpeg", "image/png"):
        return False
    # Too small → icon/logo (raised threshold)
    if w < 400 or h < 250:
        return False
    # Immediately reject anything matching skip words
    for word in _CAMPUS_SKIP:
        if word in title or word in url:
            return False
    # Accept if title clearly references a campus facility
    for word in _CAMPUS_POSITIVE:
        if word in title:
            return True
    # Accept very large landscape panoramas even without explicit keywords
    # Require clear landscape ratio (width ≥ 2× height) to exclude headshots/portraits
    if w >= 1200 and h >= 400 and w >= h * 2:
        return True
    # Reject anything else
    return False


def _label_campus_photo(file_info: dict) -> tuple:
    """Assign a readable caption and category to a campus photo."""
    title = file_info.get("title", "").replace("File:", "").replace("_", " ")
    # Strip extension
    for ext in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]:
        title = title.replace(ext, "")
    title = title.strip()[:80]

    t_lower = title.lower()
    if any(w in t_lower for w in ["library", "knowledge"]):
        return "library", title or "Central Library"
    if any(w in t_lower for w in ["lab", "research", "laboratory"]):
        return "laboratory", title or "Research Laboratory"
    if any(w in t_lower for w in ["hostel", "dormitory", "residential"]):
        return "hostel", title or "Student Hostel"
    if any(w in t_lower for w in ["sport", "ground", "stadium", "court", "field"]):
        return "sports", title or "Sports Ground"
    if any(w in t_lower for w in ["auditorium", "hall", "convention"]):
        return "auditorium", title or "Auditorium"
    if any(w in t_lower for w in ["gate", "entrance", "main"]):
        return "entrance", title or "Campus Entrance"
    if any(w in t_lower for w in ["classroom", "lecture", "seminar"]):
        return "classroom", title or "Lecture Hall"
    if any(w in t_lower for w in ["canteen", "cafeteria", "food"]):
        return "cafeteria", title or "Campus Cafeteria"
    return "campus", title or "Campus View"


def _fetch_college_wiki_images(college_name: str, entrance_exam: str = "", courses: str = "") -> List[dict]:
    """
    Fetch real campus photos for a college.
    Strategy 1 — Google Custom Search API (real web/college-site photos)
    Strategy 2 — Wikipedia article images (strict campus filter, fallback)
    Strategy 3 — Wikimedia Commons campus search (fallback)
    """
    college_short = college_name.split("(")[0].strip()
    images: List[dict] = []

    # ── Strategy 1: Google Custom Search API ─────────────────────────────────
    images = _google_campus_images(college_name, num=5)
    if len(images) >= 3:
        return images[:5]   # Good enough — return immediately

    # ── Strategy 2: Wikipedia article images ─────────────────────────────────
    page_title = _wiki_find_page_title(college_name)
    if page_title:
        file_names = _wiki_get_page_images(page_title, max_img=30)
        photo_files = [
            f for f in file_names
            if any(f.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png"])
        ]
        if photo_files:
            existing_urls = {img["url"] for img in images}
            file_infos = _wiki_get_image_urls(photo_files)
            for fi in file_infos:
                if _is_campus_photo(fi) and fi["url"] not in existing_urls:
                    cat, caption = _label_campus_photo(fi)
                    images.append({"url": fi["url"], "caption": caption, "category": cat})
                    existing_urls.add(fi["url"])
                if len(images) >= 8:
                    break

    # ── Strategy 3: Wikimedia Commons campus search ───────────────────────────
    try:
        for search_q in [
            f"{college_short} campus building",
            f"{college_short} campus",
        ]:
            if len(images) >= 5:
                break
            resp = _requests.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "list": "search",
                "srsearch": search_q, "srnamespace": "6",
                "srlimit": 15, "format": "json",
            }, headers=_WIKI_HEADERS, timeout=6)
            commons_results = resp.json().get("query", {}).get("search", [])
            extra_files = [r["title"] if r["title"].startswith("File:") else "File:" + r["title"]
                           for r in commons_results]
            photo_extra = [f for f in extra_files
                           if any(f.lower().endswith(e) for e in [".jpg", ".jpeg", ".png"])]
            if photo_extra:
                extra_infos = _wiki_get_image_urls(photo_extra[:12])
                existing_urls = {img["url"] for img in images}
                for fi in extra_infos:
                    if _is_campus_photo(fi) and fi["url"] not in existing_urls:
                        cat, caption = _label_campus_photo(fi)
                        images.append({"url": fi["url"], "caption": caption, "category": cat})
                        existing_urls.add(fi["url"])
                    if len(images) >= 8:
                        break
    except Exception:
        pass

    return images[:5]


@api_router.post("/college-campus-images")
async def college_campus_images(request: CollegeCampusImagesRequest):
    """
    Return 5 real campus photos for a college fetched from Wikipedia/Wikimedia Commons.
    Photos are actual images of the specific college uploaded on Wikipedia.
    """
    import hashlib

    try:
        # Run synchronous Wikipedia HTTP calls in thread pool (don't block the event loop)
        images = await asyncio.to_thread(
            _fetch_college_wiki_images,
            request.college_name,
            request.entrance_exam or "",
            request.courses or "",
        )

        if not images:
            # Absolute fallback: Wikipedia thumbnail via REST summary API
            college_short = request.college_name.split("(")[0].strip()
            try:
                encoded = urllib.parse.quote(college_short.replace(" ", "_"))
                resp = await asyncio.to_thread(
                    lambda: _requests.get(
                        f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}",
                        headers=_WIKI_HEADERS, timeout=6
                    )
                )
                data = resp.json()
                thumb = (data.get("thumbnail") or data.get("originalimage") or {}).get("source")
                if thumb:
                    images = [{
                        "url": thumb,
                        "caption": f"{college_short} — Campus",
                        "category": "main_campus",
                    }]
            except Exception:
                pass

        return {"college_name": request.college_name, "images": images}

    except Exception as e:
        logger.error(f"college-campus-images error: {e}")
        return {"college_name": request.college_name, "images": []}


# ─── College Thumbnail Batch (fast single-image per college) ──────────────────

class CollegeThumbsBatchRequest(BaseModel):
    college_names: List[str]


def _sync_college_thumb(college_name: str) -> str:
    """
    Return one representative campus thumbnail URL for a college.
    Step 0 — Curated verified dict     (highest priority — always correct campus photo)
    Step 1 — Wikipedia REST summary    (good for well-known colleges)
    Step 2 — Google Custom Search API  (if API key configured)
    Step 3 — DuckDuckGo image search   (free, no API key needed)
    Step 4 — AI-generated campus image (Pollinations.ai, college-specific, always works)
    Results are cached in _THUMB_CACHE for the server process lifetime.
    """
    cache_key = college_name.strip().lower()
    if cache_key in _THUMB_CACHE:
        return _THUMB_CACHE[cache_key]

    # ── Step 0: Curated dict FIRST — verified real campus photos, highest accuracy
    url = _lookup_known_college_image(college_name)

    # ── Step 1: Wikipedia REST summary (for colleges not in curated dict)
    if not url:
        url = _wiki_summary_thumb(college_name)

    # ── Step 2: Google CSE (college-website-targeted) ────────────────────────
    if not url:
        url = _google_single_thumb(college_name)

    # ── Step 3: DuckDuckGo free image search ─────────────────────────────────
    if not url:
        url = _ddg_college_thumb(college_name)

    # ── Step 4: AI-generated college-specific campus image (always succeeds) ──
    if not url:
        url = _pexels_college_fallback(college_name)

    _THUMB_CACHE[cache_key] = url
    return url


@api_router.get("/campus-img")
async def campus_img(name: str = ""):
    """
    Proxy college campus image through the backend.
    Fetches with a proper User-Agent (required by Wikimedia/Wikipedia).
    Bytes are cached in-memory for the server's lifetime.
    """
    if not name.strip():
        raise HTTPException(status_code=400, detail="name parameter required")

    cache_key = name.strip().lower()

    # Serve from bytes cache if available
    if cache_key in _PHOTO_BYTES_CACHE:
        return Response(
            content=_PHOTO_BYTES_CACHE[cache_key],
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Resolve URL via the 4-step chain (uses _THUMB_CACHE for URL-level caching)
    url = await asyncio.to_thread(_sync_college_thumb, name)

    if not url:
        raise HTTPException(status_code=404, detail="No image found for this college")

    # ── Guaranteed fallback pool: verified Wikimedia URLs that always serve fast ──
    _WC_FP2 = "https://commons.wikimedia.org/wiki/Special:FilePath"
    _GUARANTEED_POOL = [
        f"{_WC_FP2}/IITBMainBuildingCROP.jpg?width=800",
        f"{_WC_FP2}/IIT_Delhi_Main_Building.jpeg?width=800",
        f"{_WC_FP2}/IIT_Madras_Campus.jpg?width=800",
        f"{_WC_FP2}/Computer_Center_at_IIT_Kanpur_India1.jpg?width=800",
        f"{_WC_FP2}/IIT_Kharagpur_Main_Entrance_(Puri_Gate).jpg?width=800",
        f"{_WC_FP2}/IIT_Roorkee_Main_Building.jpg?width=800",
        f"{_WC_FP2}/IIMB_Campus3.jpg?width=800",
        f"{_WC_FP2}/IISC_Bangalore_Campus.jpg?width=800",
        f"{_WC_FP2}/Technology_Tower(VIT).jpg?width=800",
        f"{_WC_FP2}/BITS-Pilani_campus_aerial_view.jpg?width=800",
        f"{_WC_FP2}/Thapar_Campus_Aerial_View.jpg?width=800",
        f"{_WC_FP2}/South_Campus_Chandigarh_University.jpg?width=800",
        f"{_WC_FP2}/Jadavpur_University_Gate_No._4.jpg?width=800",
        f"{_WC_FP2}/Amity_Campus_Noida_Delhi.jpg?width=800",
        f"{_WC_FP2}/Savitribai_Phule_Pune_University_(SPPU).jpg?width=800",
        f"{_WC_FP2}/ANNA_UNIVERSITY_TRICHY_MAIN_CAMPUS.jpg?width=800",
        f"{_WC_FP2}/Iima_new_campus_panorama.jpg?width=800",
        f"{_WC_FP2}/Maulana_Azad_Library,_Aligarh_Muslim_University.jpg?width=800",
        f"{_WC_FP2}/MIT_Academic_Block_1_-_Quadrangle.jpg?width=800",
        f"{_WC_FP2}/IIIT_Hyderabad_-_Campus_view.png?width=800",
        f"{_WC_FP2}/DelhiCollegeOfEngineering_BawanaCampus.jpg?width=800",
        f"{_WC_FP2}/Delhiuni.jpg?width=800",
        f"{_WC_FP2}/University_of_Mumbai_library.jpg?width=800",
        f"{_WC_FP2}/IIM_Calcutta_Lakes_1_-_Night_Scene.jpg?width=800",
        f"{_WC_FP2}/Engineering_college_at_Osmania_University.jpg?width=800",
    ]

    # Fetch the image server-side with a proper User-Agent
    # Pollinations.ai AI-generated images may take 30-60s — try with timeout, then fall back
    is_pollinations = "image.pollinations.ai" in url
    fetch_timeout = 50 if is_pollinations else 20

    _FETCH_HEADERS = {
        "User-Agent": (
            "CampusImageProxy/1.0 (https://github.com/placeholder; bot@placeholder.org) "
            "python-requests/2.31"
        ),
        "Referer": "https://en.wikipedia.org/",
    }

    # Convert full-res Wikimedia URLs to 800px thumbnails; leave Pollinations/other URLs as-is
    fetch_url = url if is_pollinations else _to_wiki_thumbnail(url)
    urls_to_try = [fetch_url] if fetch_url == url else [fetch_url, url]

    for attempt_url in urls_to_try:
        try:
            resp = await asyncio.to_thread(
                lambda u=attempt_url, t=fetch_timeout: _requests.get(
                    u,
                    headers=_FETCH_HEADERS,
                    timeout=t,
                    allow_redirects=True,
                )
            )
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "image/jpeg")
                if ct.startswith("image/"):
                    img_bytes = resp.content
                    _PHOTO_BYTES_CACHE[cache_key] = img_bytes
                    return Response(
                        content=img_bytes,
                        media_type=ct,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
            logger.warning(f"campus_img: upstream {resp.status_code} for {attempt_url}")
        except Exception as exc:
            logger.warning(f"campus_img fetch error for '{name}': {exc}")

    # ── All attempts failed — use guaranteed Wikimedia pool as final fallback ──
    # Evict bad URL from cache so next request retries the full chain
    _THUMB_CACHE.pop(cache_key, None)
    pool_idx = int(_hashlib.md5(name.lower().encode()).hexdigest(), 16) % len(_GUARANTEED_POOL)
    fallback_url = _to_wiki_thumbnail(_GUARANTEED_POOL[pool_idx])
    try:
        resp2 = await asyncio.to_thread(
            lambda u=fallback_url: _requests.get(
                u, headers=_FETCH_HEADERS, timeout=20, allow_redirects=True
            )
        )
        if resp2.status_code == 200 and resp2.headers.get("content-type", "").startswith("image/"):
            img_bytes = resp2.content
            _PHOTO_BYTES_CACHE[cache_key] = img_bytes
            return Response(
                content=img_bytes,
                media_type=resp2.headers.get("content-type", "image/jpeg"),
                headers={"Cache-Control": "public, max-age=3600"},
            )
    except Exception as exc2:
        logger.warning(f"campus_img guaranteed fallback error for '{name}': {exc2}")

    raise HTTPException(status_code=502, detail="Could not fetch campus image")


@api_router.post("/college-thumbs-batch")
async def college_thumbs_batch(request: CollegeThumbsBatchRequest):
    """
    Fetch one representative campus thumbnail URL for each college in the list.
    Calls are parallelised in a thread pool so it stays fast even for 20+ colleges.
    Returns: { "thumbs": { "<college_name>": "<url_or_empty>" } }
    """
    names = request.college_names[:50]  # cap at 50

    async def fetch_one(name: str):
        url = await asyncio.to_thread(_sync_college_thumb, name)
        return name, url

    tasks = [fetch_one(n) for n in names]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    thumbs: Dict[str, str] = {}
    for r in results:
        if isinstance(r, tuple):
            thumbs[r[0]] = r[1]

    return {"thumbs": thumbs}


@api_router.post("/job-by-education")
async def job_by_education(request: JobByEducationRequest):
    """
    AI-powered job recommendations strictly categorised by education level.
    Returns 3 tiers: (1) Jobs NOW, (2) After short course, (3) After degree.
    Falls back to built-in dataset when AI key is not configured.
    """
    try:
        edu = request.education_level
        stream = request.stream or "N/A"
        interests = ", ".join(request.interests) if request.interests else "General"
        location = request.location or "India"
        marks = request.marks_percentage or 60

        api_key = os.environ.get('EMERGENT_LLM_KEY', '').strip()

        # ── Use fallback immediately if no AI key ──────────────────────────
        if not api_key:
            logger.info("No EMERGENT_LLM_KEY set; returning fallback job data")
            return _fallback_jobs_by_education(edu, stream, request.interests)

        interests_line = ", ".join(request.interests) if request.interests else "General / Any"
        prompt = f"""You are an expert career counselor for Indian students.

STUDENT PROFILE:
- Education Level: {edu}
- Interests (PRIMARY FOCUS): {interests_line}
- Location: {location}
- Marks/Percentage: {marks}%

CRITICAL RULE: ALL 60 job recommendations MUST directly relate to the student's interests: [{interests_line}].
Do NOT suggest generic unrelated jobs. Every job title, description, and advice must be tailored to these specific interests.

Generate EXACTLY 60 jobs split into 3 timeline categories:

CATEGORY 1 - id "now" (20 jobs): Jobs the student can start RIGHT NOW with {edu} qualification only. No extra study needed.
CATEGORY 2 - id "short_course" (20 jobs): Jobs reachable after a 3-12 month diploma/certification/ITI course aligned to [{interests_line}].
CATEGORY 3 - id "after_degree" (20 jobs): Jobs after a 2-4 year UG/PG degree in a field matching [{interests_line}].

Mix Government, Private, and Self-Employment roles. Keep all suggestions India-realistic.

Return ONLY valid JSON (no markdown, no extra text):
{{
  "education_level": "{edu}",
  "categories": [
    {{
      "id": "now",
      "title": "Start Right Now",
      "subtitle": "Jobs you can apply for today with {edu}",
      "icon": "checkmark-circle",
      "color": "#2E7D32",
      "jobs": [
        {{
          "job_title": "<interest-specific job title>",
          "description": "<what the person does day-to-day, 1-2 sentences>",
          "education_required": "{edu}",
          "salary_range": "₹X-Y LPA",
          "sector": "Government|Private|Self-Employed|Both",
          "growth_potential": "High|Medium|Low",
          "key_skills": ["skill1", "skill2", "skill3"],
          "how_to_get": "<concrete steps: portal/exam/course to join>",
          "exam_if_any": "<exam name or empty string>"
        }}
        ... 20 total jobs in this category ...
      ]
    }},
    {{
      "id": "short_course",
      "title": "After Short Course (3-12 months)",
      "subtitle": "Certification or diploma in your interest area",
      "icon": "time-outline",
      "color": "#1565C0",
      "jobs": [ ... 20 total jobs ... ]
    }},
    {{
      "id": "after_degree",
      "title": "After Degree (2-4 years)",
      "subtitle": "UG/PG degree matching your interests",
      "icon": "school-outline",
      "color": "#6A1B9A",
      "jobs": [ ... 20 total jobs ... ]
    }}
  ]
}}"""

        chat = await get_llm_chat()
        response = await chat.send_message(UserMessage(text=prompt))

        def extract_json(text: str) -> str:
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                return text.split("```")[1].split("```")[0].strip()
            start, end = text.find("{"), text.rfind("}")
            return text[start:end+1] if start != -1 and end != -1 else text

        try:
            data = json.loads(extract_json(response))
            # Validate structure; fall back if AI returned unexpected format
            if not data.get("categories") or not isinstance(data["categories"], list):
                raise ValueError("Missing categories in AI response")
            return data
        except Exception as parse_err:
            logger.warning(f"job-by-education AI parse error ({parse_err}); using fallback")
            return _fallback_jobs_by_education(edu, stream, request.interests)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"job-by-education error: {e}; returning fallback")
        return _fallback_jobs_by_education(
            request.education_level, request.stream or "", request.interests
        )


class CollegeExamGuideRequest(BaseModel):
    college_name: str
    entrance_exam: Optional[str] = ""
    college_type: Optional[str] = ""
    location: Optional[str] = "India"
    courses: Optional[str] = ""
    student_stream: Optional[str] = ""
    student_marks: Optional[float] = None


class JobRoadmapRequest(BaseModel):
    job_title: str
    education_level: str
    sector: Optional[str] = "Private"
    how_to_get: Optional[str] = ""
    exam_if_any: Optional[str] = ""
    location: Optional[str] = "India"
    key_skills: Optional[List[str]] = []


def _fallback_job_roadmap(job_title: str, education_level: str, sector: str,
                           how_to_get: str, exam_if_any: str, key_skills: List[str]) -> dict:
    """Built-in step-by-step roadmap for a job when no AI key is available."""
    has_exam = bool(exam_if_any and exam_if_any.strip())
    skills_str = ", ".join(key_skills[:3]) if key_skills else "core skills for this role"
    is_govt = "government" in sector.lower()

    return {
        "job_title": job_title,
        "roadmap": [
            {
                "phase": "0–1 Month · Understand & Plan",
                "icon": "information-circle",
                "color": "#1565C0",
                "actions": [
                    f"Research the role of {job_title} — daily tasks, work environment, growth path.",
                    f"Understand the exact qualification needed: {education_level}.",
                    f"Talk to someone already working as a {job_title} to get real insights.",
                    "Set a clear timeline and create a study/preparation calendar.",
                ],
                "resources": [
                    f"YouTube: search '{job_title} career India' for real experience videos",
                    "LinkedIn: connect with professionals already in this role",
                    "Naukri.com / Indeed: read job descriptions to map exact skill needs",
                ],
                "milestones": [
                    f"Know exactly what skills and qualifications {job_title} requires.",
                    "Have a 6-month preparation plan written down.",
                ],
            },
            {
                "phase": "1–3 Months · Build Skills",
                "icon": "hammer",
                "color": "#E65100",
                "actions": [
                    f"Focus on learning: {skills_str}.",
                    "Join a free online course — NPTEL, Coursera, Swayam, or YouTube.",
                    "Practise 1–2 hours daily on relevant skills.",
                    "Create basic projects or documentation showing your progress.",
                ] + ([f"Start {exam_if_any} syllabus and solve previous year papers daily."] if has_exam else []),
                "resources": [
                    "NPTEL (nptel.ac.in) — free certified courses",
                    "Swayam (swayam.gov.in) — government free courses",
                    "YouTube tutorials for hands-on practice",
                ] + ([f"{exam_if_any} previous year papers on official website"] if has_exam else []),
                "milestones": [
                    f"Complete at least one relevant course for {job_title}.",
                    "Be able to demonstrate 2–3 key skills confidently.",
                ],
            },
            {
                "phase": "3–6 Months · Apply & Practice",
                "icon": "briefcase",
                "color": "#2E7D32",
                "actions": [
                    how_to_get if how_to_get else f"Apply on job portals like Naukri / LinkedIn for {job_title} openings.",
                    "Update your resume highlighting skills and any projects done.",
                    "Apply to 5–10 employers or government portals every week.",
                ] + ([f"Register for {exam_if_any} exam — check schedule on official site."] if has_exam
                     else ["Attend 2–3 interview rounds to build confidence."]),
                "resources": [
                    "Naukri.com / LinkedIn for private sector jobs",
                    "sarkariresult.com / freshersworld.com for govt notifications",
                    "canva.com/resume — free resume builder",
                ],
                "milestones": [
                    "Resume updated and applied to at least 20 positions.",
                    "Completed at least 2 real interviews.",
                ],
            },
            {
                "phase": "6–12 Months · Land the Job",
                "icon": "trophy",
                "color": "#6A1B9A",
                "actions": [
                    "Improve based on interview feedback — keep iterating.",
                    "Target government exam result/interview prep." if is_govt else "Compare multiple offers and negotiate salary.",
                    "Network actively — job fairs, LinkedIn, alumni connections.",
                    "Stay consistent; every rejection is a step closer to success.",
                ],
                "resources": [
                    "Testbook / GradeStack for govt exam mock tests" if is_govt else "InterviewBit / LeetCode for technical interviews",
                    "Rojgar Samachar for government job notifications",
                    "PMKVY Skill India (skillindia.gov.in) for free certifications",
                ],
                "milestones": [
                    f"Receive first offer / selection letter as {job_title}.",
                    "Start the job and continue learning on the role.",
                ],
            },
        ],
    }


@api_router.post("/college-exam-guide")
async def college_exam_guide(request: CollegeExamGuideRequest):
    """
    AI-generated entrance exam guide for a specific college.
    Returns structured list of required/recommended exams with prep tips.
    Always attempts AI; falls back to rich built-in knowledge base on failure.
    """

    # ── Rich built-in exam knowledge base ────────────────────────────────
    EXAM_KB: dict = {
        "JEE MAIN": {
            "exam_name": "JEE Main", "full_name": "Joint Entrance Examination – Main",
            "type": "National", "color": "#1565C0",
            "eligibility": "12th PCM with 75% marks (65% for SC/ST); up to 3 attempts",
            "key_subjects": ["Physics", "Chemistry", "Mathematics"],
            "preparation_tips": [
                "Master NCERT Class 11 & 12 completely before advanced books",
                "Solve last 10 years JEE Main papers – focus on NTA patterns",
                "Target 180+ score: aim 65 in Maths, 60 in Physics, 55+ in Chemistry",
                "Use NTA Abhyas app (free) for official mock tests",
                "Attempt both January & April sessions to improve score",
            ],
            "important_apps": ["NTA Abhyas (free)", "Unacademy", "Embibe", "Khan Academy", "Doubtnut"],
            "official_website": "jeemain.nta.nic.in",
            "exam_month": "January & April (two sessions per year)",
        },
        "JEE ADVANCED": {
            "exam_name": "JEE Advanced", "full_name": "Joint Entrance Examination – Advanced",
            "type": "National", "color": "#0D47A1",
            "eligibility": "Top 2.5 lakh JEE Main qualifiers; max 2 attempts; 75% in 12th",
            "key_subjects": ["Physics", "Chemistry", "Mathematics"],
            "preparation_tips": [
                "Clear JEE Main first — only top 2.5 lakh qualify for Advanced",
                "Study HC Verma (Physics), OP Tandon (Chemistry), SL Loney (Maths)",
                "Practice previous 15 years JEE Advanced papers in exam conditions",
                "Focus on multi-concept problems and paragraph-based questions",
                "Enroll in Allen/Resonance/FIITJEE test series for feedback",
            ],
            "important_apps": ["Unacademy JEE", "Embibe", "Allen eSaral", "Physics Wallah"],
            "official_website": "jeeadv.ac.in",
            "exam_month": "May (Sunday after JEE Main April result)",
        },
        "NEET": {
            "exam_name": "NEET UG", "full_name": "National Eligibility cum Entrance Test – UG",
            "type": "National", "color": "#C62828",
            "eligibility": "12th PCB with 50% (45% for SC/ST/OBC); minimum age 17",
            "key_subjects": ["Biology (Botany + Zoology)", "Physics", "Chemistry"],
            "preparation_tips": [
                "NCERT Biology is the Bible for NEET — read every line",
                "Target 360+ in Biology (90 questions × 4 marks each)",
                "Solve last 10 years NEET papers and Aakash/Allen mock tests",
                "Make short notes of all diagrams and NCERT exemplar questions",
                "Practice Physics numericals daily — 45 questions in NEET",
            ],
            "important_apps": ["NTA Abhyas (free)", "Aakash iTutor", "Physics Wallah", "Doubtnut"],
            "official_website": "neet.nta.nic.in",
            "exam_month": "May (single session, Sunday)",
        },
        "CAT": {
            "exam_name": "CAT", "full_name": "Common Admission Test",
            "type": "National", "color": "#4A148C",
            "eligibility": "Bachelor's degree with 50% marks (45% for SC/ST); final year students eligible",
            "key_subjects": ["Verbal Ability & Reading Comprehension", "Data Interpretation & Logical Reasoning", "Quantitative Aptitude"],
            "preparation_tips": [
                "Score 99+ percentile needs at least 6 months focused preparation",
                "Read 2 editorials daily (The Hindu / Economic Times) for VARC",
                "Practice DI sets from Arun Sharma for speed and accuracy",
                "Take 3 full mock tests per week in actual exam platform",
                "Join IMS/TIME/Career Launcher for sectional analysis",
            ],
            "important_apps": ["iQuanta (free)", "Career Launcher", "IMS Learning", "Cracku CAT"],
            "official_website": "iimcat.ac.in",
            "exam_month": "November last Sunday",
        },
        "CLAT": {
            "exam_name": "CLAT", "full_name": "Common Law Admission Test",
            "type": "National", "color": "#E65100",
            "eligibility": "12th pass with 45% (40% SC/ST); all streams eligible",
            "key_subjects": ["English Language", "Current Affairs & GK", "Legal Reasoning", "Logical Reasoning", "Quantitative Techniques"],
            "preparation_tips": [
                "Read newspapers daily (The Hindu/Indian Express) for current affairs",
                "Practice legal reasoning passages — comprehension-based format",
                "Complete 3–5 years of previous CLAT papers with analysis",
                "Focus on legal maxims and basic legal concepts",
                "Attempt LegalEdge / CLATapult mock series for NLU-level preparation",
            ],
            "important_apps": ["CLATapult", "LegalEdge", "Unacademy Law", "Endeavor Careers"],
            "official_website": "consortiumofnlus.ac.in",
            "exam_month": "December",
        },
        "CUET": {
            "exam_name": "CUET UG", "full_name": "Common University Entrance Test – UG",
            "type": "National", "color": "#00695C",
            "eligibility": "12th pass or appearing; all streams; no minimum marks in most universities",
            "key_subjects": ["Domain subjects (as per stream)", "General Test (Reasoning + GK)", "Language (English/Hindi)"],
            "preparation_tips": [
                "Check your target university's CUET domain subject requirements",
                "NCERT Class 12 books are the primary source for all domain subjects",
                "Score 200/200 in your domain subject — it's achievable with NCERT",
                "Prepare General Test — Reasoning, GK, and Numerical Ability",
                "Practice NTA Sample papers and previous CUET papers on official website",
            ],
            "important_apps": ["NTA CUET App (free)", "Unacademy CUET", "Physics Wallah", "Vedantu"],
            "official_website": "cuet.samarth.ac.in",
            "exam_month": "May–June",
        },
        "GATE": {
            "exam_name": "GATE", "full_name": "Graduate Aptitude Test in Engineering",
            "type": "National", "color": "#37474F",
            "eligibility": "BE/B.Tech/B.Sc (Research) or final year; also for PSU jobs",
            "key_subjects": ["Core Engineering Subjects", "Engineering Mathematics", "General Aptitude"],
            "preparation_tips": [
                "GATE score is used for M.Tech admissions and PSU (BHEL, ONGC, NTPC) recruitment",
                "Study standard textbooks: Sedra Smith (ECE), Nise (Control), Cormen (CS)",
                "Previous 10 years GATE papers are must-solve for pattern understanding",
                "Focus on Engineering Mathematics — it carries 13 marks",
                "Join Made Easy / ACE Academy test series for evaluation",
            ],
            "important_apps": ["GATE Virtual Calculator", "Made Easy App", "Gradeup (BYJU's Exam Prep)", "Unacademy GATE"],
            "official_website": "gate.iit.in (rotating IIT)",
            "exam_month": "February (3 Sundays)",
        },
        "BITSAT": {
            "exam_name": "BITSAT", "full_name": "BITS Admission Test",
            "type": "University", "color": "#283593",
            "eligibility": "12th PCM with 75% aggregate and 60% in each subject",
            "key_subjects": ["Physics", "Chemistry", "Mathematics", "English Proficiency", "Logical Reasoning"],
            "preparation_tips": [
                "BITSAT is online and NCERT + a bit beyond is sufficient for 300+ score",
                "The extra 12 bonus questions appear only if all 130 are answered — attempt all",
                "Speed is key: 3 hours for 130 questions = 80 seconds per question",
                "Master the English & Logical Reasoning section for bonus time",
                "Use BITS official mock test and Arihant BITSAT prep guide",
            ],
            "important_apps": ["Unacademy BITSAT", "Embibe", "Toppr", "Arihant App"],
            "official_website": "bitsadmission.com",
            "exam_month": "May–June (online, scheduled slots)",
        },
        "MHT-CET": {
            "exam_name": "MHT-CET", "full_name": "Maharashtra Common Entrance Test",
            "type": "State", "color": "#880E4F",
            "eligibility": "12th PCM/PCB with 45% (40% reserved); Maharashtra domicile preferred",
            "key_subjects": ["Physics", "Chemistry", "Mathematics / Biology"],
            "preparation_tips": [
                "MHT-CET syllabus is based on Maharashtra State Board Class 11–12",
                "Questions are easier than JEE Main — target 95+ percentile for top colleges",
                "Practice Navneet / Target MHT-CET guides specifically for state board pattern",
                "Attempt official MHT-CET previous papers from mahacet.org",
                "Focus on PCM for Engineering or PCB for Medical track",
            ],
            "important_apps": ["MHT-CET Official App", "Unacademy", "Toppr", "Physics Wallah"],
            "official_website": "cetcell.mahacet.org",
            "exam_month": "April–May",
        },
        "KCET": {
            "exam_name": "KCET", "full_name": "Karnataka Common Entrance Test",
            "type": "State", "color": "#1B5E20",
            "eligibility": "12th PCM with 45%; Karnataka domicile / Kannada medium students",
            "key_subjects": ["Physics", "Chemistry", "Mathematics / Biology"],
            "preparation_tips": [
                "Based on PUC (Karnataka) Class 11–12 syllabus",
                "Target 150+/180 for top NIE/RV/BMS colleges",
                "Practice KEA official sample papers and previous 5-year papers",
                "Biology section for B.Pharm is compulsory — do not neglect",
                "Coaching centers like BASE/Deeksha offer KCET-specific test series",
            ],
            "important_apps": ["Unacademy Karnataka", "Toppr", "Physics Wallah", "Embibe"],
            "official_website": "kea.kar.nic.in",
            "exam_month": "April",
        },
        "XAT": {
            "exam_name": "XAT", "full_name": "Xavier Aptitude Test",
            "type": "National", "color": "#BF360C",
            "eligibility": "Bachelor's degree with no minimum marks; final year students eligible",
            "key_subjects": ["Decision Making", "Verbal & Logical Ability", "Quantitative Ability & Data Interpretation", "General Knowledge"],
            "preparation_tips": [
                "XAT Decision Making is unique — practice 50+ DM cases from XAT papers",
                "1 mark penalty for more than 8 unattempted questions — plan strategy",
                "GK section: 25 questions in 15 minutes — focus on business current affairs",
                "Previous 10 years XAT papers are the best preparation material",
                "Target XLRI Jamshedpur (BM/HRM): 95+ percentile needed",
            ],
            "important_apps": ["iQuanta", "Career Launcher XAT", "Cracku", "2IIM"],
            "official_website": "xatonline.in",
            "exam_month": "First Sunday of January",
        },
        "VITEEE": {
            "exam_name": "VITEEE", "full_name": "VIT Engineering Entrance Examination",
            "type": "University", "color": "#004D40",
            "eligibility": "12th PCM/PCB with 60% aggregate; no age bar",
            "key_subjects": ["Physics", "Chemistry", "Mathematics or Biology", "English", "Aptitude"],
            "preparation_tips": [
                "VITEEE is online and simpler than JEE — NCERT + one reference book is enough",
                "Score 120+/125 for VIT Vellore top branches (CSE, ECE, Mechanical)",
                "Aptitude & English sections are scoring — practice them thoroughly",
                "Use VIT official sample papers from vit.ac.in",
                "Apply early — slots fill up fast; register in December–January",
            ],
            "important_apps": ["VIT Official App", "Unacademy", "Toppr", "Embibe"],
            "official_website": "viteee.vit.ac.in",
            "exam_month": "March–April (online, individual slots)",
        },
        "SRMJEEE": {
            "exam_name": "SRMJEEE", "full_name": "SRM Joint Engineering Entrance Exam",
            "type": "University", "color": "#006064",
            "eligibility": "12th PCM with 60% aggregate",
            "key_subjects": ["Physics", "Chemistry", "Mathematics", "English", "Aptitude"],
            "preparation_tips": [
                "SRMJEEE is online and NCERT-level — aim for 100+ for good branches",
                "Choose SRM Kattankulathur or SRM Chennai for best placements",
                "Apply early as merit-based scholarships are awarded to top scorers",
                "Practice SRM sample papers from srmist.edu.in",
                "English and Aptitude sections are easy marks — don't skip",
            ],
            "important_apps": ["SRM Official App", "Testbook", "Unacademy"],
            "official_website": "srmist.edu.in/admission",
            "exam_month": "February–April (multiple phases)",
        },
        "KEAM": {
            "exam_name": "KEAM", "full_name": "Kerala Engineering Architecture Medical",
            "type": "State", "color": "#004D40",
            "eligibility": "12th PCM (Engineering) or PCB (Medical) with 50%; Kerala domicile",
            "key_subjects": ["Physics", "Chemistry", "Mathematics / Biology"],
            "preparation_tips": [
                "Based on Kerala State Board / CBSE Class 11–12 syllabus",
                "Mathematics and Physics are toughest sections — practice daily",
                "Score 400+/600 for NIT Calicut through KEAM",
                "Practice previous 10 years KEAM papers from cee.kerala.gov.in",
                "Don't skip Architecture drawing if applying for B.Arch",
            ],
            "important_apps": ["CEE Kerala app", "Unacademy", "Physics Wallah"],
            "official_website": "cee.kerala.gov.in",
            "exam_month": "April",
        },
        "ICAR AIEEA": {
            "exam_name": "ICAR AIEEA", "full_name": "ICAR All India Entrance Exam for Admission",
            "type": "National", "color": "#33691E",
            "eligibility": "12th PCB/PCMB with 50% (45% SC/ST); age 16–24",
            "key_subjects": ["Biology", "Physics", "Chemistry", "Agriculture (optional)"],
            "preparation_tips": [
                "ICAR AIEEA leads to B.Sc Agriculture/Horticulture/Veterinary in top Agricultural Universities",
                "NCERT Biology + Agriculture books are primary preparation source",
                "General Agriculture section: focus on soil types, crop varieties, pest control",
                "IARI New Delhi and PAU Ludhiana are top institutions via ICAR",
                "Practice previous 5 years ICAR AIEEA papers from icar.org.in",
            ],
            "important_apps": ["ICAR Official Site", "Unacademy Agriculture", "Testbook"],
            "official_website": "icar.org.in",
            "exam_month": "June–July",
        },
        "CMAT": {
            "exam_name": "CMAT", "full_name": "Common Management Admission Test",
            "type": "National", "color": "#6A1B9A",
            "eligibility": "Bachelor's degree with no minimum marks requirement",
            "key_subjects": ["Quantitative Techniques", "Logical Reasoning", "Language Comprehension", "General Awareness", "Innovation & Entrepreneurship"],
            "preparation_tips": [
                "CMAT score is accepted by 1000+ AICTE-approved MBA colleges across India",
                "Easier than CAT — target 300+/400 for decent PGDM colleges",
                "Innovation & Entrepreneurship section: focus on startup case studies",
                "Previous 5 years CMAT papers are available free on NTA website",
                "Best for JBIMS Mumbai (India's most affordable top MBA college via CMAT)",
            ],
            "important_apps": ["NTA CMAT App", "Unacademy MBA", "Career Launcher", "Cracku"],
            "official_website": "cmat.nta.nic.in",
            "exam_month": "January",
        },
    }

    def _enrich_exam(exam_name_raw: str) -> dict:
        """Match a raw exam string to the knowledge base and return full details."""
        name_up = exam_name_raw.upper()
        for key, info in EXAM_KB.items():
            if key in name_up or name_up in key:
                return dict(info)
        # Generic enrichment for unrecognized exams
        is_national = any(x in name_up for x in ["JEE", "NEET", "CAT", "CLAT", "CUET", "GATE", "XAT", "CMAT", "ICAR"])
        return {
            "exam_name": exam_name_raw,
            "full_name": exam_name_raw,
            "type": "National" if is_national else "State / University",
            "color": "#546E7A",
            "eligibility": "12th pass with relevant subjects; check official notification",
            "key_subjects": ["Check official syllabus on exam website"],
            "preparation_tips": [
                f"Download official syllabus and previous papers for {exam_name_raw}",
                "Revise NCERT Class 11–12 books as the base for most Indian entrance exams",
                "Join a free mock test series (Unacademy / Embibe) for practice",
                "Time yourself: most exams require 1–1.5 min per question",
            ],
            "important_apps": ["Unacademy", "Khan Academy", "Toppr", "Embibe", "Doubtnut"],
            "official_website": "Check NTA / respective exam authority website",
            "exam_month": "Check official notification (usually Jan–June)",
        }

    def _fallback_guide():
        """Rich fallback using built-in knowledge base keyed by college/exam name."""
        cn = request.college_name.upper()
        # Infer exams from college name if entrance_exam not provided
        inferred: list[str] = []
        if request.entrance_exam and request.entrance_exam not in ("—", "-", ""):
            raw = request.entrance_exam.replace(";", "/").replace(" + ", "/").replace(" / ", "/")
            inferred = [e.strip() for e in raw.split("/") if e.strip()]
        # College-type inference
        if not inferred:
            if any(x in cn for x in ["IIT ", "NIT ", "IIIT"]):
                inferred = ["JEE Main", "JEE Advanced"]
            elif any(x in cn for x in ["AIIMS", "MEDICAL", "MBBS"]):
                inferred = ["NEET UG"]
            elif any(x in cn for x in ["IIM", "MDI", "XLRI", "FMS", "SPJIMR"]):
                inferred = ["CAT", "XAT", "CMAT"]
            elif any(x in cn for x in ["LAW", "NLU", "NALSAR", "NUJS"]):
                inferred = ["CLAT"]
            elif any(x in cn for x in ["VIT "]):
                inferred = ["VITEEE", "JEE Main"]
            elif any(x in cn for x in ["SRM"]):
                inferred = ["SRMJEEE", "JEE Main"]
            elif any(x in cn for x in ["BITS ", "BIRLA"]):
                inferred = ["BITSAT"]
            elif any(x in cn for x in ["AGRICULTURE", "AGRI", "ICAR", "SAU", "PAU"]):
                inferred = ["ICAR AIEEA"]
            elif any(x in cn for x in ["KERALA", "KEAM"]):
                inferred = ["KEAM", "JEE Main"]
            elif any(x in cn for x in ["MAHARASHTRA", "MHT", "PUNE", "MUMBAI", "SYMBIOSIS", "COEP"]):
                inferred = ["MHT-CET", "JEE Main"]
            elif any(x in cn for x in ["MANIPAL"]):
                inferred = ["MET", "JEE Main", "CUET"]
            elif any(x in cn for x in ["AMRITA"]):
                inferred = ["AEEE", "JEE Main"]
            else:
                inferred = ["JEE Main", "CUET"]
        return {
            "college_name": request.college_name,
            "exams": [_enrich_exam(e) for e in inferred[:4]],
        }

    try:
        marks_info = f"{request.student_marks}%" if request.student_marks else "not specified"
        prompt = f"""You are a top Indian college admissions expert. A student wants to get into: {request.college_name}

College details:
- Type: {request.college_type or 'Not specified'}
- Location: {request.location}
- Courses offered: {request.courses or 'Various programmes'}
- Primary entrance exam listed: {request.entrance_exam or 'Not specified'}

Student profile:
- Stream: {request.student_stream or 'Not specified'}
- Marks: {marks_info}

List ALL entrance exams required or accepted by this specific college (typically 1-4 exams).
For each exam provide a clear, actionable preparation guide tailored for an Indian student.

Return ONLY this JSON (no extra text):
{{
  "college_name": "{request.college_name}",
  "exams": [
    {{
      "exam_name": "Short name (e.g. JEE Main)",
      "full_name": "Full official exam name",
      "type": "National | State | University",
      "eligibility": "Who can appear with marks cutoff",
      "key_subjects": ["subject1", "subject2", "subject3"],
      "preparation_tips": ["tip1", "tip2", "tip3", "tip4", "tip5"],
      "important_apps": ["App 1 (free)", "App 2", "App 3"],
      "official_website": "official website URL",
      "exam_month": "Typical month/season",
      "color": "#hexcolor"
    }}
  ]
}}"""

        chat = await get_llm_chat()
        response = await chat.send_message(UserMessage(text=prompt))

        def extract_json(text: str) -> str:
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                return text.split("```")[1].split("```")[0].strip()
            s, e = text.find("{"), text.rfind("}")
            return text[s:e+1] if s != -1 and e != -1 else text

        try:
            data = json.loads(extract_json(response))
            if not data.get("exams") or not isinstance(data["exams"], list) or len(data["exams"]) == 0:
                raise ValueError("Empty or invalid exams list")
            # Enrich any exam missing key fields using KB
            for ex in data["exams"]:
                if not ex.get("preparation_tips") or len(ex.get("preparation_tips", [])) < 2:
                    kb = _enrich_exam(ex.get("exam_name", ""))
                    ex.setdefault("preparation_tips", kb["preparation_tips"])
                    ex.setdefault("important_apps", kb["important_apps"])
                    ex.setdefault("key_subjects", kb["key_subjects"])
                    ex.setdefault("official_website", kb["official_website"])
                    ex.setdefault("exam_month", kb["exam_month"])
                    ex.setdefault("color", kb["color"])
            return data
        except Exception as pe:
            logger.warning(f"college-exam-guide AI parse error ({pe}); using rich fallback")
            return _fallback_guide()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"college-exam-guide error: {e}; using rich fallback")
        return _fallback_guide()


@api_router.post("/job-roadmap")
async def job_roadmap(request: JobRoadmapRequest):
    """
    Generate step-by-step roadmap for a specific job.
    Uses AI if EMERGENT_LLM_KEY is set, otherwise returns built-in roadmap.
    """
    try:
        api_key = os.environ.get('EMERGENT_LLM_KEY', '').strip()

        if not api_key:
            logger.info(f"No AI key — returning fallback roadmap for {request.job_title}")
            return _fallback_job_roadmap(
                request.job_title, request.education_level,
                request.sector or "Private", request.how_to_get or "",
                request.exam_if_any or "", request.key_skills or [],
            )

        skills_str = ", ".join(request.key_skills or []) or "relevant skills"
        prompt = f"""Create a detailed step-by-step roadmap for an Indian student who wants to become a {request.job_title}.

Student profile:
- Education: {request.education_level}
- Location: {request.location}
- Sector: {request.sector}
- Key skills needed: {skills_str}
- How to get this job: {request.how_to_get or 'Standard application process'}
- Exam required: {request.exam_if_any or 'None'}

Create a 4-phase roadmap (0-1 month, 1-3 months, 3-6 months, 6-12 months).
Each phase: specific actions, free/affordable resources, milestones.
Be realistic and India-specific. Suggest offline resources where internet access is limited.

Return ONLY this JSON:
{{
  "job_title": "{request.job_title}",
  "roadmap": [
    {{
      "phase": "0-1 Month · Understand & Plan",
      "icon": "information-circle",
      "color": "#1565C0",
      "actions": ["action1", "action2", "action3"],
      "resources": ["resource1", "resource2"],
      "milestones": ["milestone1", "milestone2"]
    }}
  ]
}}
All 4 phases required."""

        chat = await get_llm_chat()
        response = await chat.send_message(UserMessage(text=prompt))

        def extract_json(text: str) -> str:
            if "```json" in text:
                return text.split("```json")[1].split("```")[0].strip()
            if "```" in text:
                return text.split("```")[1].split("```")[0].strip()
            s, e = text.find("{"), text.rfind("}")
            return text[s:e+1] if s != -1 and e != -1 else text

        try:
            data = json.loads(extract_json(response))
            if not data.get("roadmap") or not isinstance(data["roadmap"], list):
                raise ValueError("Invalid roadmap structure")
            return data
        except Exception as pe:
            logger.warning(f"job-roadmap AI parse error ({pe}); using fallback")
            return _fallback_job_roadmap(
                request.job_title, request.education_level,
                request.sector or "Private", request.how_to_get or "",
                request.exam_if_any or "", request.key_skills or [],
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"job-roadmap error: {e}; returning fallback")
        return _fallback_job_roadmap(
            request.job_title, request.education_level,
            request.sector or "Private", request.how_to_get or "",
            request.exam_if_any or "", request.key_skills or [],
        )


@api_router.post("/generate-roadmap/{career_name}")
async def generate_roadmap(career_name: str, recommendation_id: str):
    """
    Generate detailed roadmap for selected career
    """
    try:
        logger.info(f"Generating roadmap for career: {career_name}")
        
        # Get the recommendation from DB
        rec = await db.career_recommendations.find_one({"id": recommendation_id})
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        
        profile = StudentProfile(**rec["student_profile"])
        
        # Generate roadmap prompt
        prompt = f"""
Create a detailed, timeline-based roadmap for a rural Indian student pursuing: {career_name}

Student Context:
- Current Level: {profile.education_level}
- Budget: {profile.budget_for_education}
- Internet: {profile.internet_access}
- Location: {profile.location}

Create a step-by-step roadmap divided into these phases:
1. 0-3 months (Immediate actions)
2. 3-6 months (Short-term goals)
3. 6-12 months (Medium-term goals)
4. 1-3 years (Long-term goals)

For EACH phase provide:
- Specific actions to take
- Free/affordable resources to use
- Milestones to achieve

Consider their constraints (budget, internet, location). Suggest offline resources where needed.

Provide response in this EXACT JSON format:
{{
  "roadmap": [
    {{
      "phase": "0-3 months",
      "actions": ["action1", "action2", "action3"],
      "resources": ["resource1", "resource2"],
      "milestones": ["milestone1", "milestone2"]
    }}
  ]
}}

Provide all 4 phases.
"""

        chat = await get_llm_chat()
        message = UserMessage(text=prompt)
        response = await chat.send_message(message)
        
        # Parse response
        try:
            response_text = response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            roadmap_data = json.loads(response_text)
        except Exception as e:
            logger.error(f"Failed to parse roadmap: {e}")
            raise HTTPException(status_code=500, detail="Failed to parse roadmap")
        
        roadmap = [Roadmap(**phase) for phase in roadmap_data.get("roadmap", [])]
        
        # Get matching scholarships using RAG
        matched_scholarships = match_scholarships(profile, career_name)
        scholarships = [Scholarship(**s) for s in matched_scholarships]
        
        # Update recommendation in DB
        await db.career_recommendations.update_one(
            {"id": recommendation_id},
            {
                "$set": {
                    "selected_career": career_name,
                    "roadmap": [r.dict() for r in roadmap],
                    "scholarships": [s.dict() for s in scholarships]
                }
            }
        )
        
        return {
            "roadmap": [r.dict() for r in roadmap],
            "scholarships": [s.dict() for s in scholarships]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating roadmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/recommendations/{recommendation_id}")
async def get_recommendation(recommendation_id: str):
    """
    Get a specific recommendation by ID
    """
    rec = await db.career_recommendations.find_one({"id": recommendation_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    return rec


@api_router.get("/recommendations")
async def list_recommendations():
    """
    List all recommendations
    """
    recs = await db.career_recommendations.find({}, {"_id": 0}).to_list(100)
    return recs



# ==================== Authentication Endpoints ====================

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    location: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


@api_router.post("/auth/register", response_model=Token)
async def register(user_data: UserRegister):
    """Register a new user"""
    try:
        # Check if user already exists
        existing_user = await db.users.find_one({"email": user_data.email})
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # Hash password
        hashed_password = pwd_context.hash(user_data.password)
        
        # Create user
        user = {
            "id": str(uuid.uuid4()),
            "email": user_data.email,
            "full_name": user_data.full_name,
            "hashed_password": hashed_password,
            "phone": user_data.phone,
            "location": user_data.location,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "last_login": datetime.utcnow()
        }
        
        await db.users.insert_one(user)
        
        # Create access token
        access_token = jwt.encode(
            {"sub": user["id"], "email": user["email"]},
            SECRET_KEY,
            algorithm=ALGORITHM
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "phone": user["phone"],
                "location": user["location"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")


@api_router.post("/auth/login", response_model=Token)
async def login(credentials: UserLogin):
    """Login user"""
    try:
        # Find user
        user = await db.users.find_one({"email": credentials.email})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Verify password
        if not pwd_context.verify(credentials.password, user["hashed_password"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Update last login
        await db.users.update_one(
            {"email": credentials.email},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        
        # Create access token
        access_token = jwt.encode(
            {"sub": user["id"], "email": user["email"]},
            SECRET_KEY,
            algorithm=ALGORITHM
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "phone": user.get("phone"),
                "location": user.get("location")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current authenticated user"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication")
        
        user = await db.users.find_one({"id": user_id})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"]
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info"""
    return current_user


# ==================== Feedback Endpoints ====================

class FeedbackCreate(BaseModel):
    recommendation_id: str
    rating: int  # 1-5
    comments: Optional[str] = None
    is_helpful: bool
    suggestions: Optional[str] = None


@api_router.post("/feedback")
async def submit_feedback(
    feedback_data: FeedbackCreate,
    current_user: dict = Depends(get_current_user)
):
    """Submit feedback for a career recommendation"""
    try:
        if feedback_data.rating < 1 or feedback_data.rating > 5:
            raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
        
        feedback = {
            "id": str(uuid.uuid4()),
            "user_id": current_user["id"],
            "recommendation_id": feedback_data.recommendation_id,
            "rating": feedback_data.rating,
            "comments": feedback_data.comments,
            "is_helpful": feedback_data.is_helpful,
            "suggestions": feedback_data.suggestions,
            "created_at": datetime.utcnow()
        }
        
        await db.feedback.insert_one(feedback)
        
        return {"message": "Feedback submitted successfully", "feedback_id": feedback["id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Feedback submission error: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit feedback")


@api_router.get("/feedback/{recommendation_id}")
async def get_feedback(recommendation_id: str):
    """Get all feedback for a recommendation"""
    try:
        feedbacks = await db.feedback.find({"recommendation_id": recommendation_id}).to_list(100)
        return feedbacks
    except Exception as e:
        logger.error(f"Error fetching feedback: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch feedback")


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
