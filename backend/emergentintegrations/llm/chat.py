"""
Stub implementation of emergentintegrations.llm.chat
Returns profile-aware responses based on education, stream, location, and interests.
"""
import json
import re


class UserMessage:
    def __init__(self, text: str):
        self.text = text


class LlmChat:
    def __init__(self, api_key=None, session_id=None, system_message=None):
        self.api_key = api_key
        self.session_id = session_id
        self.system_message = system_message
        self._model = None

    def with_model(self, provider: str, model: str):
        self._model = f"{provider}/{model}"
        return self

    def _extract(self, text: str, label: str) -> str:
        """Extract a field value from LLM prompt text."""
        pattern = rf"{label}:\s*(.+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    async def send_message(self, message: UserMessage) -> str:
        text = message.text

        # ── Roadmap request ──────────────────────────────────────────
        if "roadmap" in text.lower() or "phase" in text.lower():
            career_name = ""
            m = re.search(r"pursuing:\s*(.+)", text)
            if m:
                career_name = m.group(1).strip()
            return json.dumps(self._build_roadmap(career_name))

        # ── Career recommendation request ────────────────────────────
        education = self._extract(text, "Education")
        stream    = self._extract(text, "Stream")
        interests = self._extract(text, "Interests")
        location  = self._extract(text, "Location")
        budget    = self._extract(text, "Budget for Education")
        marks_str = self._extract(text, "Marks")
        marks = 0
        m = re.search(r"(\d+(?:\.\d+)?)", marks_str)
        if m:
            marks = float(m.group(1))

        ed  = education.lower()
        st  = stream.lower()
        int_lower = interests.lower()

        careers = []
        exams   = []

        # ─── 10th level ──────────────────────────────────────────────
        if "10th" in ed:
            if any(w in int_lower for w in ["computer", "coding", "tech", "it", "software"]):
                careers = [
                    _career("ITI Computer Operator & Programming",
                            "1-year ITI course in computer operator and programming assistant (COPA).",
                            "After 10th, ITI COPA is the fastest way into the IT sector with low cost.",
                            9, "₹10k-50k", "1-2 years",
                            ["Computer Basics", "MS Office", "Typing", "Internet"]),
                    _career("Diploma in Computer Science (Polytechnic)",
                            "3-year polytechnic diploma offering software and hardware fundamentals.",
                            "Government polytechnics are low-cost and widely available in your region.",
                            8, "₹20k-1 Lakh", "3 years",
                            ["C Programming", "Networking", "Database", "Web Basics"]),
                    _career("Banking / Clerical Services",
                            "Join public-sector banks as clerk, data entry operator, or office assistant.",
                            "After 12th/ITI, IBPS clerical exams are accessible with basic commerce/math.",
                            7, "₹30k-1 Lakh coaching", "2-3 years",
                            ["Arithmetic", "General English", "Banking Awareness", "Computer"]),
                ]
                exams = ["ITI NCVT Exam", "Polytechnic Entrance (State)", "IBPS Clerk", "SSC CHSL"]
            elif any(w in int_lower for w in ["nurse", "health", "medical", "doctor"]):
                careers = [
                    _career("GNM Nursing",
                            "3.5-year General Nursing & Midwifery diploma — entry via 10+2 Science.",
                            "High demand for nurses; government hospitals hire via state nursing councils.",
                            9, "₹50k-2 Lakhs", "3.5 years",
                            ["Biology", "Patient Care", "Anatomy", "First Aid"]),
                    _career("Pharmacy (D.Pharm)",
                            "2-year diploma in pharmacy — work in hospitals, clinics, medical stores.",
                            "Lower cost than B.Pharm; government diploma colleges available in every district.",
                            8, "₹30k-1 Lakh", "2 years",
                            ["Chemistry", "Pharmacology", "Dispensing", "Patient Counselling"]),
                    _career("Lab Technician (DMLT)",
                            "2-year diploma in medical lab technology — high demand in rural hospitals.",
                            "DMLT graduates can start own pathology lab or join government hospitals.",
                            8, "₹30k-80k", "2 years",
                            ["Biology", "Lab Skills", "Microbiology", "Blood Analysis"]),
                ]
                exams = ["State CPNET", "AIIMS Nursing Entrance", "State Para-Medical CET", "Staff Nurse Recruitment"]
            elif any(w in int_lower for w in ["farm", "agri", "crop", "animal"]):
                careers = [
                    _career("ITI Agriculture Technician",
                            "1-2 year ITI course covering modern farming, soil science, and crop management.",
                            "Highly suitable for students from agricultural families — direct application.",
                            9, "₹10k-40k", "1-2 years",
                            ["Soil Science", "Crop Management", "Irrigation", "Fertilisers"]),
                    _career("Veterinary Field Technician",
                            "Para-vet diploma to assist veterinarians, vaccination drives and animal health.",
                            "Government para-vet schemes are free in many states for rural candidates.",
                            8, "₹20k-50k", "2 years",
                            ["Zoology", "Animal Health", "Vaccination", "Livestock"]),
                    _career("Krishi Sahayak / Agriculture Supervisor",
                            "State government agriculture department field roles.",
                            "Stable government employment with rural postings that suit your background.",
                            7, "₹50k-1.5 Lakhs coaching", "2-3 years",
                            ["Agronomy", "Crop Science", "General Knowledge", "Aptitude"]),
                ]
                exams = ["ICAR AIEEA", "State Agriculture CET", "IBPS AFO", "Krishi Sahayak Exam"]
            else:
                careers = [
                    _career("Polytechnic Diploma (General)",
                            "3-year diploma in engineering branches: civil, electrical, mechanical.",
                            "After 10th, polytechnic is the most accessible technical path with job guarantee.",
                            9, "₹20k-1 Lakh", "3 years",
                            ["Mathematics", "Physics", "Workshop Skills", "Drawing"]),
                    _career("Teacher (Primary / TET)",
                            "Complete 12th then D.El.Ed (2 years) to become a primary school teacher.",
                            "High demand for government teachers in rural India; job security and pension.",
                            8, "₹50k-1.5 Lakhs", "4-5 years",
                            ["Communication", "English", "Pedagogy", "Subject Knowledge"]),
                    _career("Government Services (SSC/State PSC)",
                            "Central and state government jobs via SSC CGL, CHSL, MTS, and state PSC exams.",
                            "Stable career with pension; accessible from any stream after 12th/graduation.",
                            7, "₹30k-1 Lakh coaching", "3-4 years",
                            ["Aptitude", "General Knowledge", "English", "Current Affairs"]),
                ]
                exams = ["Polytechnic State CET", "SSC MTS", "State TET", "IBPS Clerk"]

        # ─── 12th Science ────────────────────────────────────────────
        elif "12th" in ed and ("science" in st or any(w in int_lower for w in ["engineer", "tech", "software", "coding", "computer", "it"])):
            if marks >= 75 or any(w in int_lower for w in ["engineer", "software", "coding", "computer", "it"]):
                careers = [
                    _career("Software Engineer (B.Tech CSE)",
                            "4-year B.Tech in Computer Science — India's highest-demand career.",
                            "Government NIT/IIIT seats via JEE are affordable. Remote jobs boost income.",
                            9, "₹2-8 Lakhs (govt college)", "4 years",
                            ["Mathematics", "C++/Python", "Data Structures", "DSA", "Problem Solving"]),
                    _career("MBBS Doctor",
                            "5.5-year MBBS from government medical college after clearing NEET.",
                            "After NEET, government MBBS costs ₹10-50k/year. High societal respect.",
                            8 if marks >= 70 else 6, "₹50k-5 Lakhs (govt)", "5.5 years",
                            ["Biology", "Chemistry", "Physics", "NCERT Preparation", "NEET"]),
                    _career("B.Sc + Government Research / Teaching",
                            "3-year B.Sc then M.Sc, NET/SET for lecturer or DRDO/ISRO scientist roles.",
                            "Low-cost option compared to B.Tech; government research careers are stable.",
                            7, "₹50k-2 Lakhs", "5-6 years",
                            ["Mathematics/Physics/Chemistry", "Research Skills", "GATE/NET"]),
                ]
                exams = ["JEE Mains", "JEE Advanced", "NEET", "BITSAT", "State CET", "VITEEE"]
            else:
                careers = [
                    _career("B.Sc Nursing",
                            "4-year B.Sc Nursing from government college — best healthcare career path.",
                            "Government B.Sc Nursing colleges are very affordable; placement guaranteed.",
                            9, "₹30k-1.5 Lakhs (govt)", "4 years",
                            ["Biology", "Anatomy", "Patient Care", "Nursing Practice"]),
                    _career("Software Engineer (Diploma + Lateral Entry)",
                            "Polytechnic diploma then lateral entry B.Tech to cut cost by 1 year.",
                            "If JEE is tough, lateral entry into government engineering is budget-friendly.",
                            8, "₹1-4 Lakhs", "4-5 years",
                            ["Programming Basics", "Mathematics", "Problem Solving"]),
                    _career("Government Teacher (Science — TGT/PGT)",
                            "B.Sc + B.Ed then TGT/PGT state examination for science teaching post.",
                            "Science teachers are in high demand; secure government salary + pension.",
                            8, "₹1-3 Lakhs", "5 years",
                            ["Subject Knowledge", "Pedagogy", "CTET/STET", "Communication"]),
                ]
                exams = ["State CET", "NEET", "AIIMS B.Sc Nursing", "CTET", "State TGT/PGT"]

        # ─── 12th Commerce ───────────────────────────────────────────
        elif "12th" in ed and "commerce" in st:
            careers = [
                _career("Chartered Accountant (CA)",
                        "CA Foundation → Intermediate → Final — India's top finance career.",
                        "Commerce students can start CA Foundation right after 12th; no college needed.",
                        8, "₹1-3 Lakhs (ICAI fees)", "5 years",
                        ["Accountancy", "Taxation", "Auditing", "Financial Reporting", "Law"]),
                _career("Banking Officer (IBPS PO / SBI PO)",
                        "Graduate then clear IBPS PO exam for officer-grade bank role.",
                        "Bank officers earn ₹40k-80k/month with transfer flexibility nationwide.",
                        9, "₹50k-2 Lakhs", "3-4 years",
                        ["Arithmetic", "General English", "Banking Awareness", "Reasoning"]),
                _career("BBA + MBA (Business Management)",
                        "3-year BBA then 2-year MBA; CAT/MAT/CMAT for top B-schools.",
                        "Management careers are high-paying in retail, logistics, FMCG, and startups.",
                        7, "₹3-10 Lakhs total", "5 years",
                        ["Communication", "Management", "Data Analysis", "Leadership"]),
            ]
            exams = ["CA Foundation", "IBPS PO", "SBI PO", "BBA CET", "CUET", "CMAT"]

        # ─── 12th Arts ───────────────────────────────────────────────
        elif "12th" in ed and ("art" in st or "humanit" in st):
            careers = [
                _career("UPSC Civil Services (IAS/IPS/IFS)",
                        "Most prestigious Indian career — district collector, IPS officer, diplomat.",
                        "Arts graduates have a natural advantage in UPSC optional subjects like History, PoliSci.",
                        7, "₹1-5 Lakhs coaching", "3-5 years after graduation",
                        ["History", "Polity", "Geography", "Current Affairs", "Essay Writing"]),
                _career("Teacher / Lecturer (Arts — TGT/PGT)",
                        "BA + B.Ed then state TGT/PGT exam for government school teaching post.",
                        "Consistent demand; government teachers in Arts get secure salary and pension.",
                        9, "₹1-3 Lakhs", "4-5 years",
                        ["Subject Mastery", "Pedagogy", "CTET/STET", "Communication"]),
                _career("Journalism & Mass Communication",
                        "BA in Journalism then career in print, digital, TV, or social media reporting.",
                        "Growing digital media jobs in regional languages; low entry barrier with smartphones.",
                        8, "₹1-4 Lakhs", "3-4 years",
                        ["Writing", "Communication", "Regional Language", "Research", "Editing"]),
            ]
            exams = ["CUET", "UPSC CSE", "CTET/STET", "State PCS", "BJMC Entrance", "Delhi University Entrance"]

        # ─── Graduate level ──────────────────────────────────────────
        elif "graduate" in ed or "degree" in ed:
            if any(w in int_lower for w in ["tech", "software", "coding", "it", "computer"]):
                careers = [
                    _career("Software Developer (Entry Level)",
                            "Full-stack / backend developer at IT companies, startups, or freelancing.",
                            "With a CS/IT degree you can start immediately; bootcamp + projects help.",
                            9, "₹10k-50k (upskilling)", "6-12 months",
                            ["Python/Java", "Web Dev", "SQL", "Git", "Problem Solving"]),
                    _career("GATE → M.Tech / PSU Jobs",
                            "GATE score gives M.Tech admission and direct PSU recruitment (ONGC, BHEL, etc).",
                            "PSU jobs provide ₹70k+ salary with government benefits from day one.",
                            8, "₹50k-1.5 Lakhs GATE coaching", "1-2 years",
                            ["Core Engineering", "Mathematics", "Aptitude", "Subject Depth"]),
                    _career("Data Analyst / AI/ML Engineer",
                            "Emerging high-pay field combining statistics, Python, and machine learning.",
                            "Many free courses (Coursera, NPTEL) help you transition without extra degree.",
                            8, "₹20k-1 Lakh (courses)", "6-18 months",
                            ["Python", "Statistics", "SQL", "Machine Learning", "Data Visualisation"]),
                ]
                exams = ["GATE", "TCS NQT", "Infosys InfyTQ", "AMCAT", "CAT (MBA Tech)"]
            else:
                careers = [
                    _career("UPSC Civil Services",
                            "IAS/IPS/IFS officer through the most prestigious competitive exam in India.",
                            "Graduates from any stream are eligible; strong subjects give advantage.",
                            7, "₹1-5 Lakhs coaching", "2-4 years",
                            ["Current Affairs", "GS Papers", "CSAT", "Optional Subject", "Essay"]),
                    _career("Teaching — College Lecturer (NET/SET)",
                            "PhD or NET/SET qualification to teach at college/university level.",
                            "Government college lecturers earn ₹50k-1 Lakh/month + UGC benefits.",
                            8, "₹50k-2 Lakhs", "2-4 years",
                            ["Subject Mastery", "Research", "NET/SET Exam", "Communication"]),
                    _career("Banking Officer (IBPS PO / SBI PO)",
                            "Officer-grade bank role through IBPS PO or SBI PO exams.",
                            "Any graduate is eligible; high salary with job security and pension.",
                            9, "₹30k-1 Lakh coaching", "6-18 months",
                            ["Reasoning", "Quantitative Aptitude", "English", "Banking"]),
                ]
                exams = ["UPSC CSE", "IBPS PO", "SBI PO", "SSC CGL", "UGC NET", "State PSC"]

        # ─── Default / fallback ──────────────────────────────────────
        else:
            careers = [
                _career("Government Services (SSC/State PSC)",
                        "Central and state government jobs with stable income and pension.",
                        "Accessible to candidates from any background after 12th or graduation.",
                        9, "₹30k-1 Lakh coaching", "2-4 years",
                        ["Aptitude", "General Knowledge", "English", "Current Affairs"]),
                _career("Teacher (Government School — TGT/PGT)",
                        "Teach at government school level after B.Ed and state TET.",
                        "High demand in rural schools; stable government job with social respect.",
                        8, "₹1-3 Lakhs", "4-5 years",
                        ["Subject Knowledge", "Pedagogy", "Communication"]),
                _career("Banking / Insurance Sector",
                        "Banking clerk, PO, or insurance agents through IBPS/LIC exams.",
                        "White-collar income accessible from any location after graduation.",
                        8, "₹50k-1.5 Lakhs", "2-3 years",
                        ["Arithmetic", "English", "Reasoning", "Banking Knowledge"]),
            ]
            exams = ["SSC CGL", "IBPS Clerk", "CTET", "State PCS", "LIC AAO"]

        # Location-based exam additions
        loc = location.lower()
        if "bihar" in loc or "jharkhand" in loc:
            exams = list(dict.fromkeys(exams + ["BSSC CGL", "JPSC", "BPSC"]))
        elif "up" in loc or "uttar pradesh" in loc:
            exams = list(dict.fromkeys(exams + ["UPPSC", "UP Police", "UPTET"]))
        elif "rajasthan" in loc:
            exams = list(dict.fromkeys(exams + ["RPSC RAS", "Rajasthan Police", "RTET"]))
        elif "maharashtra" in loc:
            exams = list(dict.fromkeys(exams + ["MPSC", "Maharashtra TET", "MH-CET"]))
        elif "karnataka" in loc:
            exams = list(dict.fromkeys(exams + ["KPSC", "Karnataka TET", "KCET"]))
        elif "tamil" in loc or "tn" in loc:
            exams = list(dict.fromkeys(exams + ["TNPSC", "TNTET", "TNEA"]))
        elif "west bengal" in loc or "bengal" in loc:
            exams = list(dict.fromkeys(exams + ["WBCS", "WBPSC", "WB TET"]))
        elif "madhya pradesh" in loc or "mp" in loc:
            exams = list(dict.fromkeys(exams + ["MPPSC", "MP TET", "MP Police"]))

        return json.dumps({"careers": careers[:3], "entrance_exams": exams[:8]})

    def _build_roadmap(self, career_name: str) -> dict:
        cl = career_name.lower()
        if any(w in cl for w in ["software", "engineer", "developer", "it ", "cse", "tech"]):
            phases = [
                _phase("0-3 months: Foundation", ["Strengthen Mathematics & Physics", "Learn C++ or Python basics from NPTEL/YouTube", "Create a free GitHub account and push small projects"], ["NPTEL Programming courses (free)", "W3Schools, GeeksforGeeks", "NCERT Mathematics"], ["Complete 1 programming language basics", "Solve 50 easy problems on HackerRank"]),
                _phase("3-9 months: JEE/CET Preparation", ["Study JEE Mains syllabus — Physics, Chemistry, Math", "Attempt daily mock tests (Embibe, NTA app)", "Apply for government NIT/IIIT/State CET"], ["NTA JEE free mock tests", "Embibe free test series", "State Engineering CET portal"], ["Score 80%+ in 3 consecutive mock tests", "Register for JEE Mains"]),
                _phase("Year 1-4: B.Tech Degree", ["Complete B.Tech in CSE/IT from NIT/Government college", "Build 5+ projects on GitHub", "Do at least 2 internships via NaukriCampus/InternShala"], ["InternShala free internships", "NPTEL MOOCs for extra skills", "GitHub Student Pack"], ["Complete 3rd year with CGPA 7+", "Get internship confirmation"]),
                _phase("Year 4+: Career Launch", ["Apply via campus placement (CTC ₹6-25 LPA at top companies)", "Prepare for FAANG via LeetCode DSA practice", "Apply for government PSU roles via GATE if interested"], ["LeetCode, Codeforces for practice", "LinkedIn Jobs, Naukri.com", "GATE PSU recruitment portal"], ["Receive offer letter ≥ ₹6 LPA", "Clear 2 technical rounds"]),
            ]
        elif any(w in cl for w in ["doctor", "mbbs", "medical", "physician"]):
            phases = [
                _phase("0-12 months: NEET Preparation", ["Study NCERT Biology, Chemistry, Physics cover-to-cover", "Attempt 1 full-length NEET mock test daily", "Subscribe to free Allen/Aakash YouTube channels"], ["NCERT Exemplar Problems", "Allen free NEET test series", "NTA NEET mock tests (free)"], ["Score 550+ in NEET mock", "Complete all NCERT chapters"]),
                _phase("Year 1-5.5: MBBS", ["Attend MBBS lectures and clinical rotations", "Clear university exams each semester", "Join NMC-recognised hospital internship"], ["MBBS standard textbooks (Grays, Harrison)", "NMC guidelines website", "Hospital clinical rotations"], ["Pass all professional exams", "Complete 1-year rotating internship"]),
                _phase("Year 6+: Residency / PG", ["Prepare for NEET-PG for specialisation", "Apply for government hospital MD/MS seats", "Register with State Medical Council"], ["NEET-PG prep apps (PrepLadder)", "NBE official website", "State Medical Council"], ["Score 500+ in NEET-PG", "Secure MD/MS seat"]),
                _phase("Practice / Career", ["Choose specialisation or go for general practice", "Open rural clinic supported by PMJAY", "Apply for government MBBS posts"], ["PMJAY empanelment portal", "NMC licensing", "National Health Mission jobs"], ["Achieve full consultant status", "Register own clinic"]),
            ]
        elif any(w in cl for w in ["teacher", "teaching", "educator", "lecturer", "b.ed", "tet"]):
            phases = [
                _phase("0-6 months: Graduate", ["Complete/continue BA/B.Sc relevant to subject", "Study NCERT school textbooks for content mastery", "Read about National Education Policy 2020"], ["NCERT textbooks (free PDF)", "DIKSHA app (free government content)", "YouTube pedagogy lectures"], ["Complete graduation with 50%+", "Identify target subject"]),
                _phase("Year 1-2: B.Ed", ["Enroll in 2-year B.Ed from NCTE-recognised college", "Practice teaching in school internship (required)", "Prepare for CTET/State TET parallel"], ["NCTE approved college list", "CTET old papers on NTA website", "DIKSHA teacher training modules"], ["Obtain B.Ed degree", "Score 60%+ in teaching practice"]),
                _phase("0-12 months: TET Preparation", ["Solve CTET previous year papers daily", "Study Child Development & Pedagogy (CDP)", "Revise all relevant subjects"], ["NTA CTET official site", "Exampur YouTube (free)", "KVS/NVS recruitment portals"], ["Score 60%+ to clear CTET", "Apply for KVS/NVS/State government teacher posts"]),
                _phase("Career: Government Teacher", ["Apply to KVS, NVS, State Board school vacancies", "Participate in in-service training programs", "Progress to TGT → PGT → Principal scale"], ["KVS recruitment portal", "NVS navodaya.gov.in", "State Education Department"], ["Secure permanent government post", "Progress to Pay Level 7+"]),
            ]
        elif any(w in cl for w in ["upsc", "ias", "civil service", "government service", "ssc", "psc"]):
            phases = [
                _phase("0-6 months: Foundation", ["Read NCERT books Class 6-12 for GS foundation", "Subscribe to newspaper (The Hindu / Indian Express)", "Understand UPSC CSE syllabus and pattern"], ["NCERT free PDFs on ncert.nic.in", "The Hindu app (free first articles)", "UPSC official syllabus PDF"], ["Complete NCERT reading", "Decide optional subject"]),
                _phase("6-18 months: Prelims Prep", ["Study GS Paper I (History, Polity, Geography, Economy, Science)", "Solve CSAT Paper II daily", "Take full-length prelims mock tests every week"], ["Insights IAS free notes", "Vision IAS free YouTube", "ForumIAS mock tests"], ["Score 100+ in 5 consecutive mock prelims", "Register for UPSC Prelims"]),
                _phase("18-30 months: Mains Prep", ["Write 10 answers daily in exam style", "Prepare optional subject from standard books", "Join online test series for mains"], ["Forum IAS answer writing", "Drishti IAS YouTube (Hindi)", "Mrunal.org (Economy)"], ["Complete all GS papers", "Write mock mains with evaluation"]),
                _phase("Interview Preparation", ["Form mock interview panel with mentors", "Stay updated with current national/international affairs", "Join an IAS interview coaching or online programme"], ["Vajiram & Ravi interview guidance", "LBSNAA website", "PMO.gov.in for policy updates"], ["Clear interview with 200+ marks", "Final merit list selection"]),
            ]
        elif any(w in cl for w in ["banking", "bank", "ibps", "sbi po"]):
            phases = [
                _phase("0-3 months: Basics", ["Study Quantitative Aptitude, Reasoning, English basics", "Open IBPS Official portal and note exam calendar", "Practice 50 questions per section daily"], ["R.S. Agarwal Quantitative Aptitude free PDFs", "IBPS official site ibps.in", "Testbook free banking quiz"], ["Solve 100 questions/day without error", "Register on IBPS portal"]),
                _phase("3-9 months: Bank PO Preparation", ["Complete IBPS PO syllabus in all 5 sections", "Solve 20 full-length mock tests", "Learn banking awareness: RBI/SEBI/monetary policy"], ["Testbook, Oliveboard free mocks", "Banking awareness PDF (Bankers Adda)", "YouTube channels: Study IQ, Adda247"], ["Score 80+ in mock prelims", "Apply for IBPS PO official exam"]),
                _phase("Interview Round", ["Prepare banking knowledge for interview", "Work on communication skills and body language", "Stay updated on Union Budget, RBI policy"], ["BST Interviews YouTube (mock)", "PIB daily news", "RBI annual report"], ["Clear mains + clear interview", "Document verification ready"]),
                _phase("Career Growth", ["Join as Probationary Officer at Scale I (₹36-63k/month)", "Clear JAIIB and CAIIB certifications for promotion", "Target Scale II promotion in 3 years"], ["IIBF exam portal", "Bank internal training programmes", "LinkedIn banking community"], ["Achieve Scale II in 3-4 years", "CTC crosses ₹70k/month"]),
            ]
        elif any(w in cl for w in ["nurs", "gnm", "bsc nurs"]):
            phases = [
                _phase("0-3 months: NEET / AIIMS Nursing Prep", ["Study Biology, Chemistry, Physics for nursing entrance", "Check state nursing college admission notifications", "Apply for BSc Nursing / GNM entrance forms"], ["NCERT Biology, Chemistry", "AIIMS Nursing entrance papers", "Indian Nursing Council website"], ["Score 50%+ in entrance exam", "Secure seat in government nursing college"]),
                _phase("Year 1-4: B.Sc Nursing Degree", ["Study all nursing subjects + clinical postings", "Pass university exams each year", "Participate in community health postings"], ["INC curriculum guidelines", "Textbooks: Brunner & Suddarth", "Hospital clinical rotations"], ["Complete all theory + practical", "Register with State Nursing Council"]),
                _phase("Internship & Registration", ["Complete mandatory 1-year internship at recognised hospital", "Register with Indian Nursing Council", "Prepare for Staff Nurse government exams"], ["INC registration portal", "State nursing council", "AIIMS/ESIC/CGHS recruitment"], ["Get INC registration number", "Apply for government hospital positions"]),
                _phase("Career: Government Nurse", ["Apply to ESIC, CGHS, AIIMS, Railways Health", "Prepare for State PSC Staff Nurse exam", "Consider specialisation in ICU/OT/NICU"], ["NMC job portal", "ESI corporation careers", "Union Public Service Commission nursing"], ["Secure permanent government post", "Progress to Nursing Supervisor level"]),
            ]
        else:
            phases = [
                _phase("0-3 months: Foundation", ["Research career requirements and entrance exams", "Gather study materials and create study schedule", "Join free online communities for guidance"], ["NCERT textbooks (free)", "YouTube subject lectures", "Telegram study groups"], ["Finalise career goal", "Complete syllabus overview"]),
                _phase("3-9 months: Preparation", ["Study core subjects every day for 4-6 hours", "Take weekly mock tests", "Apply for entrance exam registration"], ["Test series apps (Testbook, Oliveboard)", "Study groups", "NPTEL free MOOCs"], ["Complete syllabus", "Score 60%+ in mocks"]),
                _phase("9-18 months: Apply & Admission", ["Fill all relevant entrance exam forms", "Apply to colleges/organisations", "Apply for scholarships on NSP portal"], ["College official websites", "NSP scholarships.gov.in", "State scholarship portals"], ["Submit all applications", "Appear for entrance exams"]),
                _phase("Year 2+: Career Launch", ["Complete degree or training programme", "Do internship or practical training", "Build professional network and apply for jobs"], ["LinkedIn, Naukri.com", "Campus placement cell", "Government job portals"], ["Get first placement/job", "Earn industry certification"]),
            ]
        return {"roadmap": phases}


def _career(name, desc, why, score, cost, time, skills):
    return {"career_name": name, "description": desc, "why_suitable": why,
            "feasibility_score": score, "estimated_cost": cost,
            "time_to_achieve": time, "key_skills_needed": skills}

def _phase(phase, actions, resources, milestones):
    return {"phase": phase, "actions": actions, "resources": resources, "milestones": milestones}
