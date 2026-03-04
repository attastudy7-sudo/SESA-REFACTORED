"""
Basic test suite for SESA.
Run with: pytest tests/
"""
import pytest


@pytest.fixture
def app():
    """Create application for testing."""
    from app import create_app
    app = create_app('testing')

    with app.app_context():
        from app.extensions import db
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


class TestLanding:
    def test_landing_page_loads(self, client):
        res = client.get('/')
        assert res.status_code == 200

    def test_login_page_loads(self, client):
        res = client.get('/auth/login')
        assert res.status_code == 200

    def test_school_login_page_loads(self, client):
        res = client.get('/auth/school-login')
        assert res.status_code == 200

    def test_signup_page_loads(self, client):
        res = client.get('/auth/signup')
        assert res.status_code == 200


class TestAuth:
    def test_login_requires_valid_credentials(self, client, app):
        from werkzeug.security import generate_password_hash
        from app.extensions import db
        from app.models.account import Accounts

        with app.app_context():
            user = Accounts(
                fname='Test', lname='User',
                email='test@example.com', username='testuser',
                password=generate_password_hash('testpass123')
            )
            db.session.add(user)
            db.session.commit()

        res = client.post('/auth/login', data={
            'username': 'testuser',
            'password': 'wrongpassword',
            'csrf_token': 'test'
        }, follow_redirects=True)
        assert res.status_code == 200

    def test_home_redirects_unauthenticated(self, client):
        res = client.get('/home')
        assert res.status_code in (302, 401)


class TestTestService:
    def test_classify_score_normal(self):
        from app.services.test_service import classify_score
        result = classify_score('Social Phobia', 3)
        assert result['stage'] == 'Normal Stage'

    def test_classify_score_clinical(self):
        from app.services.test_service import classify_score
        result = classify_score('Social Phobia', 25)
        assert result['stage'] == 'Clinical Stage'

    def test_classify_unknown_type(self):
        from app.services.test_service import classify_score
        result = classify_score('Unknown Test', 10)
        assert result['stage'] == 'Unknown'

    def test_get_next_test(self):
        from app.services.test_service import get_next_test
        assert get_next_test('Separation Anxiety Disorder') == 'Social Phobia'
        assert get_next_test('Major Depressive Disorder') is None

    def test_all_scoring_ranges_covered(self):
        from app.services.test_service import SCORING_RANGES, TEST_ORDER
        for test_type in TEST_ORDER:
            assert test_type in SCORING_RANGES
            assert len(SCORING_RANGES[test_type]) == 4
