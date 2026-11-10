"""Explicit live smoke test; safe to import, excluded from automated pytest runs."""
from services.ai_service import AIService, AIError
from models.schemas import APIInput
from config import Config


def main():
    try:
        suite = AIService(Config.ADAPTION_MODEL).generate(APIInput(project_name='Connection check', api_description='GET /health returns HTTP 200, application/json, with status equal to ok. No authentication. Unknown scenarios must be ineligible.', endpoint='/health'))
        print('Adaption structured generation succeeded. Validated cases:', len(suite.test_cases))
        return 0
    except AIError as error:
        print(str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
