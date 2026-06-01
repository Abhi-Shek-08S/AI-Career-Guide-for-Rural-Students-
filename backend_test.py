#!/usr/bin/env python3
"""
Backend API Testing for AI Career Guide App
Tests all backend endpoints with realistic rural student data
"""

import requests
import json
import time
import sys
from typing import Dict, Any, List

# Backend URL from frontend .env
BACKEND_URL = "https://ai-pathfinder-8.preview.emergentagent.com/api"

# Test data - realistic rural student profile
TEST_PROFILE = {
    "name": "Rajesh Kumar",
    "education_level": "12th",
    "current_class": "Class 12",
    "stream": "Science",
    "marks_percentage": 75.5,
    "subjects": ["Physics", "Chemistry", "Math"],
    "interests": ["Coding", "Problem Solving", "Teaching"],
    "location": "Bihar - Patna",
    "family_income": "1-3 Lakhs",
    "budget_for_education": "50k-1L",
    "internet_access": "Limited",
    "language_preference": "Hindi",
    "other_constraints": "Need scholarship support, limited coaching access"
}

class BackendTester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        self.results = []
        self.recommendation_id = None
        
    def log_result(self, test_name: str, success: bool, details: str, response_data: Any = None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        print(f"   Details: {details}")
        if response_data and not success:
            print(f"   Response: {response_data}")
        print()
        
        self.results.append({
            'test': test_name,
            'success': success,
            'details': details,
            'response': response_data
        })
    
    def test_api_health(self):
        """Test basic API connectivity"""
        try:
            response = self.session.get(f"{BACKEND_URL}/")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "active":
                    self.log_result("API Health Check", True, f"API is active - {data.get('message')}")
                    return True
                else:
                    self.log_result("API Health Check", False, f"Unexpected response: {data}")
                    return False
            else:
                self.log_result("API Health Check", False, f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_result("API Health Check", False, f"Connection error: {str(e)}")
            return False
    
    def test_career_recommendations(self):
        """Test POST /api/generate-career-recommendations"""
        try:
            print("Testing career recommendations generation...")
            print(f"Sending profile: {TEST_PROFILE['name']} - {TEST_PROFILE['education_level']} student")
            
            start_time = time.time()
            response = self.session.post(
                f"{BACKEND_URL}/generate-career-recommendations",
                json=TEST_PROFILE,
                timeout=60  # LLM calls can take time
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                # Validate response structure
                if not data.get("id"):
                    self.log_result("Career Recommendations", False, "Missing recommendation ID", data)
                    return False
                
                if not data.get("career_paths"):
                    self.log_result("Career Recommendations", False, "Missing career_paths", data)
                    return False
                
                career_paths = data["career_paths"]
                if len(career_paths) != 3:
                    self.log_result("Career Recommendations", False, f"Expected 3 career paths, got {len(career_paths)}", data)
                    return False
                
                # Validate each career path structure
                required_fields = ["career_name", "description", "why_suitable", "feasibility_score", 
                                 "estimated_cost", "time_to_achieve", "key_skills_needed"]
                
                for i, career in enumerate(career_paths):
                    for field in required_fields:
                        if field not in career:
                            self.log_result("Career Recommendations", False, f"Career {i+1} missing field: {field}", career)
                            return False
                    
                    # Validate feasibility score
                    score = career.get("feasibility_score")
                    if not isinstance(score, int) or score < 1 or score > 10:
                        self.log_result("Career Recommendations", False, f"Invalid feasibility_score: {score}", career)
                        return False
                    
                    # Validate key_skills_needed is a list
                    if not isinstance(career.get("key_skills_needed"), list):
                        self.log_result("Career Recommendations", False, f"key_skills_needed should be a list", career)
                        return False
                
                # Check entrance exams
                entrance_exams = data.get("entrance_exams", [])
                if not isinstance(entrance_exams, list):
                    self.log_result("Career Recommendations", False, "entrance_exams should be a list", data)
                    return False
                
                # Store recommendation ID for next test
                self.recommendation_id = data["id"]
                
                self.log_result("Career Recommendations", True, 
                              f"Generated 3 career paths in {duration:.1f}s. Careers: {[c['career_name'] for c in career_paths]}")
                return True
                
            else:
                self.log_result("Career Recommendations", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            self.log_result("Career Recommendations", False, "Request timeout (>60s)")
            return False
        except Exception as e:
            self.log_result("Career Recommendations", False, f"Error: {str(e)}")
            return False
    
    def test_roadmap_generation(self):
        """Test POST /api/generate-roadmap/{career_name}"""
        if not self.recommendation_id:
            self.log_result("Roadmap Generation", False, "No recommendation ID available from previous test")
            return False
        
        try:
            # Use first career from previous test
            career_name = "Software Developer"  # Default career name to test
            
            print(f"Testing roadmap generation for: {career_name}")
            
            start_time = time.time()
            response = self.session.post(
                f"{BACKEND_URL}/generate-roadmap/{career_name}?recommendation_id={self.recommendation_id}",
                timeout=60
            )
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                # Validate roadmap structure
                if not data.get("roadmap"):
                    self.log_result("Roadmap Generation", False, "Missing roadmap", data)
                    return False
                
                roadmap = data["roadmap"]
                if len(roadmap) != 4:
                    self.log_result("Roadmap Generation", False, f"Expected 4 phases, got {len(roadmap)}", data)
                    return False
                
                # Expected phases
                expected_phases = ["0-3 months", "3-6 months", "6-12 months", "1-3 years"]
                
                for i, phase in enumerate(roadmap):
                    # Check required fields
                    required_fields = ["phase", "actions", "resources", "milestones"]
                    for field in required_fields:
                        if field not in phase:
                            self.log_result("Roadmap Generation", False, f"Phase {i+1} missing field: {field}", phase)
                            return False
                    
                    # Validate arrays
                    for array_field in ["actions", "resources", "milestones"]:
                        if not isinstance(phase[array_field], list) or len(phase[array_field]) == 0:
                            self.log_result("Roadmap Generation", False, f"Phase {i+1} {array_field} should be non-empty list", phase)
                            return False
                
                # Check scholarships
                scholarships = data.get("scholarships", [])
                if not isinstance(scholarships, list):
                    self.log_result("Roadmap Generation", False, "scholarships should be a list", data)
                    return False
                
                if len(scholarships) < 2:
                    self.log_result("Roadmap Generation", False, f"Expected at least 2 scholarships, got {len(scholarships)}", scholarships)
                    return False
                
                # Validate scholarship structure
                scholarship_fields = ["name", "provider", "amount", "eligibility", "deadline", "application_link"]
                for i, scholarship in enumerate(scholarships[:3]):  # Check first 3
                    for field in scholarship_fields:
                        if field not in scholarship:
                            self.log_result("Roadmap Generation", False, f"Scholarship {i+1} missing field: {field}", scholarship)
                            return False
                
                self.log_result("Roadmap Generation", True, 
                              f"Generated 4-phase roadmap with {len(scholarships)} scholarships in {duration:.1f}s")
                return True
                
            else:
                self.log_result("Roadmap Generation", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            self.log_result("Roadmap Generation", False, "Request timeout (>60s)")
            return False
        except Exception as e:
            self.log_result("Roadmap Generation", False, f"Error: {str(e)}")
            return False
    
    def test_recommendation_retrieval(self):
        """Test GET /api/recommendations/{id}"""
        if not self.recommendation_id:
            self.log_result("Recommendation Retrieval", False, "No recommendation ID available")
            return False
        
        try:
            response = self.session.get(f"{BACKEND_URL}/recommendations/{self.recommendation_id}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Validate stored data
                if not data.get("id") == self.recommendation_id:
                    self.log_result("Recommendation Retrieval", False, "ID mismatch", data)
                    return False
                
                if not data.get("student_profile"):
                    self.log_result("Recommendation Retrieval", False, "Missing student_profile", data)
                    return False
                
                if not data.get("career_paths"):
                    self.log_result("Recommendation Retrieval", False, "Missing career_paths", data)
                    return False
                
                # Check if roadmap and scholarships were saved (if roadmap test passed)
                has_roadmap = bool(data.get("roadmap"))
                has_scholarships = bool(data.get("scholarships"))
                
                self.log_result("Recommendation Retrieval", True, 
                              f"Retrieved recommendation with roadmap: {has_roadmap}, scholarships: {has_scholarships}")
                return True
                
            else:
                self.log_result("Recommendation Retrieval", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("Recommendation Retrieval", False, f"Error: {str(e)}")
            return False
    
    def test_scholarship_matching_logic(self):
        """Test RAG-based scholarship matching with different profiles"""
        test_cases = [
            {
                "name": "Priya Sharma",  # Female name to test gender-based matching
                "education_level": "12th",
                "stream": "Science",
                "family_income": "1-3 Lakhs",
                "expected_scholarships": ["girls", "female", "women", "science"]
            },
            {
                "name": "Mohammed Ali",
                "education_level": "Graduate",
                "stream": "Commerce", 
                "family_income": "<1L",
                "expected_scholarships": ["minority", "graduation", "low income"]
            }
        ]
        
        all_passed = True
        
        for i, test_case in enumerate(test_cases):
            try:
                profile = TEST_PROFILE.copy()
                profile.update({
                    "name": test_case["name"],
                    "education_level": test_case["education_level"],
                    "stream": test_case["stream"],
                    "family_income": test_case["family_income"]
                })
                
                response = self.session.post(
                    f"{BACKEND_URL}/generate-career-recommendations",
                    json=profile,
                    timeout=60
                )
                
                if response.status_code == 200:
                    data = response.json()
                    rec_id = data["id"]
                    
                    # Generate roadmap to get scholarships
                    roadmap_response = self.session.post(
                        f"{BACKEND_URL}/generate-roadmap/Software Developer?recommendation_id={rec_id}",
                        timeout=60
                    )
                    
                    if roadmap_response.status_code == 200:
                        roadmap_data = roadmap_response.json()
                        scholarships = roadmap_data.get("scholarships", [])
                        
                        if len(scholarships) >= 2:
                            self.log_result(f"Scholarship Matching Case {i+1}", True, 
                                          f"Matched {len(scholarships)} scholarships for {test_case['name']}")
                        else:
                            self.log_result(f"Scholarship Matching Case {i+1}", False, 
                                          f"Only {len(scholarships)} scholarships matched for {test_case['name']}")
                            all_passed = False
                    else:
                        self.log_result(f"Scholarship Matching Case {i+1}", False, 
                                      f"Roadmap generation failed: {roadmap_response.status_code}")
                        all_passed = False
                else:
                    self.log_result(f"Scholarship Matching Case {i+1}", False, 
                                  f"Career generation failed: {response.status_code}")
                    all_passed = False
                    
            except Exception as e:
                self.log_result(f"Scholarship Matching Case {i+1}", False, f"Error: {str(e)}")
                all_passed = False
        
        return all_passed
    
    def run_all_tests(self):
        """Run all backend tests"""
        print("=" * 60)
        print("AI CAREER GUIDE - BACKEND API TESTING")
        print("=" * 60)
        print(f"Backend URL: {BACKEND_URL}")
        print(f"Test Profile: {TEST_PROFILE['name']} ({TEST_PROFILE['education_level']} {TEST_PROFILE['stream']})")
        print("=" * 60)
        print()
        
        # Run tests in sequence
        tests = [
            ("API Health Check", self.test_api_health),
            ("Career Recommendations Generation", self.test_career_recommendations),
            ("Roadmap Generation", self.test_roadmap_generation),
            ("Recommendation Retrieval", self.test_recommendation_retrieval),
            ("Scholarship Matching Logic", self.test_scholarship_matching_logic)
        ]
        
        passed = 0
        total = len(tests)
        
        for test_name, test_func in tests:
            print(f"Running: {test_name}")
            if test_func():
                passed += 1
            print("-" * 40)
        
        # Summary
        print("=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        print()
        
        # Failed tests details
        failed_tests = [r for r in self.results if not r['success']]
        if failed_tests:
            print("FAILED TESTS:")
            for test in failed_tests:
                print(f"❌ {test['test']}: {test['details']}")
        else:
            print("🎉 ALL TESTS PASSED!")
        
        print("=" * 60)
        
        return passed == total

if __name__ == "__main__":
    tester = BackendTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)