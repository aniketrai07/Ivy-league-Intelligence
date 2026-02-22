from pydantic import BaseModel


class Config(BaseModel):
    DB_URL: str = "sqlite:///./ivy_data.db"

    USER_AGENT: str = "IvyLeagueScraper/3.0 (student project; respectful crawler)"
    REQUEST_TIMEOUT: int = 25
    REQUEST_DELAY_SEC: float = 1.0  # polite rate limiting

    MAX_PER_UNI_RECORDS: int = 30

    # Scheduler
    SCHEDULE_MINUTES: int = 180  # every 3 hours


config = Config()