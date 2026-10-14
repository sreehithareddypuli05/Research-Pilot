import os
from dotenv import load_dotenv

load_dotenv()
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b').strip()
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://researchpilot:choose_a_strong_local_password@localhost:5432/researchpilot')
FRONTEND_ORIGIN = os.getenv('FRONTEND_ORIGIN', 'http://localhost:5173').strip()
JWT_SECRET = os.getenv('JWT_SECRET', '').strip()
JWT_EXPIRE_HOURS = max(1, int(os.getenv('JWT_EXPIRE_HOURS', '72')))
MAX_SEARCH_RESULTS = max(2, min(int(os.getenv('MAX_SEARCH_RESULTS', '4')), 6))
