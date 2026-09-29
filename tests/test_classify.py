"""Tests for centralised role classification (collectors/classify.py).

These tests pin the exclusion rules so that changes to internal-role
filtering are always intentional and documented.
"""
import unittest
from collectors.classify import is_sigma_vacancy, INTERNAL_ROLES


class SigmaVacancyTests(unittest.TestCase):
    """is_sigma_vacancy() should accept fee-earning qualified-lawyer roles
    and reject support roles, internal roles, and non-legal titles."""

    # ── Should be accepted (fee-earning) ─────────────────────────────
    def test_associate(self):
        self.assertTrue(is_sigma_vacancy('Associate'))

    def test_senior_associate(self):
        self.assertTrue(is_sigma_vacancy('Senior Associate - Employment'))

    def test_partner(self):
        self.assertTrue(is_sigma_vacancy('Partner'))

    def test_solicitor(self):
        self.assertTrue(is_sigma_vacancy('Solicitor - Corporate'))

    def test_counsel(self):
        self.assertTrue(is_sigma_vacancy('Counsel'))

    def test_legal_director(self):
        self.assertTrue(is_sigma_vacancy('Legal Director'))

    def test_barrister(self):
        self.assertTrue(is_sigma_vacancy('Barrister'))

    def test_restructuring_associate(self):
        self.assertTrue(is_sigma_vacancy('Restructuring & Insolvency Senior Associate'))

    def test_patent_litigation_associate(self):
        self.assertTrue(is_sigma_vacancy('Patent Litigation Associate'))

    def test_employment_associate(self):
        self.assertTrue(is_sigma_vacancy('Employment Associate'))

    def test_managing_associate(self):
        self.assertTrue(is_sigma_vacancy('Managing Associate - Real Estate'))

    # ── Should be rejected (internal / non-fee-earning) ──────────────
    def test_knowledge_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Knowledge Lawyer'))

    def test_senior_knowledge_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Senior Knowledge Lawyer'))

    def test_knowledge_management_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Knowledge Management Lawyer'))

    def test_psl(self):
        self.assertFalse(is_sigma_vacancy('Professional Support Lawyer'))

    def test_compliance_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Compliance Lawyer'))

    def test_compliance_attorney(self):
        self.assertFalse(is_sigma_vacancy('Compliance Attorney'))

    def test_compliance_counsel(self):
        self.assertFalse(is_sigma_vacancy('Compliance Counsel'))

    def test_risk_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Risk Lawyer'))

    def test_senior_risk_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Senior Risk Lawyer'))

    def test_conflicts_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Conflicts Lawyer'))

    def test_conflicts_attorney(self):
        self.assertFalse(is_sigma_vacancy('Conflicts Attorney - Lateral Conflicts'))

    def test_conflicts_counsel(self):
        self.assertFalse(is_sigma_vacancy('Conflicts Counsel'))

    def test_ogc_lawyer(self):
        self.assertFalse(is_sigma_vacancy('OGC Lawyer'))

    def test_content_lawyer(self):
        self.assertFalse(is_sigma_vacancy('Content Lawyer'))

    def test_general_counsel(self):
        self.assertFalse(is_sigma_vacancy('General Counsel'))

    def test_knowledge_development(self):
        self.assertFalse(is_sigma_vacancy('Knowledge Development'))

    def test_innovation_attorney(self):
        self.assertFalse(is_sigma_vacancy('Innovation Attorney'))
        self.assertFalse(is_sigma_vacancy('Innovation Attorney - Litigation'))
        self.assertFalse(is_sigma_vacancy('Knowledge & Innovation Attorney - Litigation'))

    # ── Should be rejected (support / operational roles) ─────────────
    def test_paralegal(self):
        self.assertFalse(is_sigma_vacancy('Paralegal'))

    def test_secretary(self):
        self.assertFalse(is_sigma_vacancy('Legal Secretary'))

    def test_hr_business_partner(self):
        self.assertFalse(is_sigma_vacancy('HR Business Partner'))

    def test_trainee(self):
        self.assertFalse(is_sigma_vacancy('Trainee Solicitor'))

    def test_summer_associate(self):
        self.assertFalse(is_sigma_vacancy('Summer Associate'))
        self.assertFalse(is_sigma_vacancy('2027 2L Summer Associate Positions'))

    def test_marketing_manager(self):
        self.assertFalse(is_sigma_vacancy('Marketing Manager'))

    def test_it_analyst(self):
        self.assertFalse(is_sigma_vacancy('IT Analyst'))

    def test_recruiting_and_people_roles(self):
        self.assertFalse(is_sigma_vacancy('Partner Recruiting Manager'))
        self.assertFalse(is_sigma_vacancy('Partner Recruiting Senior Specialist - 18 Month Fixed Term Contract'))
        self.assertFalse(is_sigma_vacancy('Partner Integration Manager'))
        self.assertFalse(is_sigma_vacancy('Legal Recruiting & Associate Life Assistant'))
        self.assertFalse(is_sigma_vacancy('Senior Lateral Recruiting & Associate Life Coordinator'))
        self.assertFalse(is_sigma_vacancy('Manager, Legal Recruiting & Associate Life'))
        self.assertFalse(is_sigma_vacancy('Associate Development Manager'))

    # ── Should be rejected (no lawyer keyword) ───────────────────────
    def test_business_analyst(self):
        self.assertFalse(is_sigma_vacancy('Business Analyst'))

    def test_accountant(self):
        self.assertFalse(is_sigma_vacancy('Senior Accountant'))

    def test_receptionist(self):
        self.assertFalse(is_sigma_vacancy('Receptionist'))

    def test_empty_string(self):
        self.assertFalse(is_sigma_vacancy(''))


class InternalRolesPatternTests(unittest.TestCase):
    """Verify INTERNAL_ROLES regex directly for completeness."""

    def test_risk_associate(self):
        self.assertTrue(INTERNAL_ROLES.search('Risk Associate'))

    def test_compliance_officer(self):
        self.assertTrue(INTERNAL_ROLES.search('Compliance Officer'))

    def test_conflicts_analyst(self):
        self.assertTrue(INTERNAL_ROLES.search('Conflicts Analyst'))

    def test_pricing_lawyer(self):
        self.assertTrue(INTERNAL_ROLES.search('Pricing Lawyer'))

    def test_innovation_lawyer(self):
        self.assertTrue(INTERNAL_ROLES.search('Innovation Lawyer'))

    def test_litigation_associate_not_internal(self):
        self.assertFalse(INTERNAL_ROLES.search('Litigation Associate'))

    def test_corporate_partner_not_internal(self):
        self.assertFalse(INTERNAL_ROLES.search('Corporate Partner'))


if __name__ == '__main__':
    unittest.main()
