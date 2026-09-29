from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode
from collectors.harbour import HarbourCollector, HarbourConfig, ParseError, parse_board, parse_advert, extract_pqe, is_london, lawyer_title
from collectors.http import FetchError, HttpClient, OfficialRedirects
from models import ScanResult, Vacancy, utc_now
from storage import Store

FIXTURES = Path(__file__).parent / 'fixtures'
URL = 'https://apply.tlt.com/vacancies/'
CONFIG = HarbourConfig('TLT', URL, 'field_4811')
def fixture(name):
    return (FIXTURES / name).read_text()
def sample():
    return Vacancy('TLT','123','TLT-123','Associate - Employment','London, Bristol',URL+'123/associate','Employment','official title','2+ years PQE',utc_now(),True,'legal_careers','Qualified role title')
def result(vacancies=(), status='SUCCESS'):
    return ScanResult('TLT',URL,finished_at=utc_now(),status=status,vacancies=list(vacancies))
class FakeClient:
    def __init__(self, mapping):
        self.mapping, self.requests = mapping, 0
    def get(self, url):
        self.requests += 1
        value = self.mapping.get(url, FetchError('Simulated inaccessible page'))
        if isinstance(value, Exception):
            raise value
        return value

class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.board = fixture('board.html')
        self.root,self.cards,self.pages,self.current = parse_board(self.board,URL)
    def test_real_board_and_pagination(self):
        self.assertEqual(len(self.cards),12)
        self.assertEqual(self.pages,{1,2,3,4,5})
        self.assertEqual(self.cards[0]['job_id'],'6146')
        self.assertEqual(self.cards[0]['url'],URL+'6146/associate_finance_litigation')
    def test_second_page(self):
        self.assertEqual(parse_board(fixture('page2.html'),URL+'page/2/')[3],2)
    def test_explicit_zero_is_valid(self):
        self.assertEqual(parse_board(fixture('empty.html'),URL)[1],[])
    def test_block_page_not_zero(self):
        with self.assertRaises(ParseError):
            parse_board('<html>Access denied</html>',URL)
    def test_unrecognised_empty_not_success(self):
        with self.assertRaises(ParseError):
            parse_board('<form id="vacancy-search-form"></form>',URL)
    def test_broken_card_rejected(self):
        with self.assertRaises(ParseError):
            parse_board(self.board.replace('vacancy_title','changed_title'),URL)
    def test_real_advert_pqe_and_identity(self):
        vacancy,decision,_ = parse_advert(fixture('advert.html'),self.cards[0],'TLT')
        self.assertEqual(decision,'include')
        self.assertEqual(vacancy.reference,'TLT-6146')
        self.assertIn("1-3 year's PQE",vacancy.pqe)
        self.assertIn('1 year PQE +',vacancy.pqe)
        self.assertEqual(vacancy.practice_area,'Finance Litigation')
        self.assertFalse(vacancy.london)
    def test_advert_wrong_id_rejected(self):
        with self.assertRaises(ParseError):
            parse_advert(fixture('advert.html'),{**self.cards[0],'job_id':'9999'},'TLT')
    def test_missing_structured_advert_rejected(self):
        with self.assertRaises(ParseError):
            parse_advert('<html>Job no longer available</html>',self.cards[0],'TLT')
    def test_pqe_missing_is_null(self):
        self.assertIsNone(extract_pqe('<p>Join our growing team.</p>'))
    def test_pqe_full_caveat_preserved(self):
        text='Ideally 3–5 years PQE, but all levels considered.'
        self.assertEqual(extract_pqe('<p>'+text+'</p>'),text)
    def test_london_multi_office_and_remote(self):
        self.assertTrue(is_london('Bristol, London'))
        self.assertFalse(is_london('Remote'))
        self.assertFalse(is_london('Londonderry'))
    def test_missing_page_keeps_partial_discoveries(self):
        cards,_,pages,errors=HarbourCollector(CONFIG,FakeClient({})).listings(self.board)
        self.assertEqual(len(cards),12)
        self.assertEqual(pages,1)
        self.assertTrue(errors)
    def test_ignored_pagination_detected(self):
        client=FakeClient({URL+f'page/{n}/':self.board for n in range(2,6)})
        _,_,_,errors=HarbourCollector(CONFIG,client).listings(self.board)
        self.assertTrue(any('received page 1' in error for error in errors))
    def test_empty_london_complete_is_success(self):
        empty=fixture('empty.html')
        london=URL+'?'+urlencode({'c[field_4811]':'4420','submit':'search'})
        scan=HarbourCollector(CONFIG,FakeClient({URL:empty,london:empty})).collect()
        self.assertEqual(scan.status,'SUCCESS')
        self.assertTrue(scan.coverage['london_filter_complete'])
        self.assertEqual(scan.vacancies,[])
    def test_filter_failure_does_not_pass_as_zero(self):
        scan=HarbourCollector(CONFIG,FakeClient({URL:fixture('empty.html')})).collect()
        self.assertNotEqual(scan.status,'SUCCESS')
        self.assertFalse(scan.coverage['london_filter_complete'])
    def test_business_partner_is_not_lawyer(self):
        self.assertFalse(lawyer_title('HR Business Partner','business_professionals'))
        self.assertTrue(lawyer_title('Risk Lawyer','business_professionals'))
    def test_duplicate_html_attributes_use_first(self):
        from collectors.html import Tree
        node=Tree('<form id="first" id="second"></form>').root.find('form')[0]
        self.assertEqual(node.attrs['id'],'first')
    def test_network_blocked(self):
        scan=HarbourCollector(CONFIG,FakeClient({})).collect()
        self.assertEqual(scan.status,'BLOCKED')
        self.assertTrue(scan.errors)
    def test_official_host_only(self):
        with self.assertRaises(FetchError):
            HttpClient('apply.tlt.com').get('https://example.org/jobs')
    def test_redirect_host_only(self):
        with self.assertRaises(FetchError):
            OfficialRedirects('apply.tlt.com').redirect_request(None,None,302,'',{},'https://example.org')

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.store=Store(self.path)
    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
    def test_second_scan_not_new_after_reopen(self):
        _,first=self.store.save(result([sample()]))
        self.assertTrue(first[0]['is_new'])
        self.store.close()
        self.store=Store(self.path)
        _,second=self.store.save(result([sample()]))
        self.assertFalse(second[0]['is_new'])
        self.assertEqual(first[0]['first_seen'],second[0]['first_seen'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM vacancies').fetchone()[0],1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],2)
    def test_failure_and_absence_never_remove_or_recreate_new(self):
        self.store.save(result([sample()]))
        original=dict(self.store.db.execute('SELECT * FROM vacancies').fetchone())
        for status in ['BLOCKED','PARTIAL','LIMITED','SUCCESS']:
            self.store.save(result([],status))
            self.assertEqual(dict(self.store.db.execute('SELECT * FROM vacancies').fetchone()),original)
        _,rows=self.store.save(result([sample()]))
        self.assertFalse(rows[0]['is_new'])
    def test_title_url_location_changes_not_new(self):
        self.store.save(result([sample()]))
        changed=sample()
        changed.title,changed.url,changed.location='Senior Associate',URL+'123/new-slug','Bristol'
        _,rows=self.store.save(result([changed]))
        self.assertFalse(rows[0]['is_new'])
        self.assertEqual(self.store.db.execute('SELECT title FROM vacancies').fetchone()[0],'Senior Associate')
    def test_new_id_is_new(self):
        self.store.save(result([sample()]))
        new=sample()
        new.job_id='124'
        _,rows=self.store.save(result([sample(),new]))
        self.assertEqual([r['is_new'] for r in rows],[False,True])
    def test_partial_scan_saves_observed_only(self):
        self.store.save(result([sample()]))
        new=sample()
        new.job_id='124'
        self.store.save(result([new],'PARTIAL'))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM vacancies').fetchone()[0],2)
    def test_transaction_rollback(self):
        with self.assertRaises(Exception):
            self.store.save(result([sample(),sample()]))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM vacancies').fetchone()[0],0)
if __name__=='__main__':
    unittest.main()
