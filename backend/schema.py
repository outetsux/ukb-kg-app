from pydantic import BaseModel, Field, field_validator


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

    @field_validator('question')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Enter a question.')
        return value.strip()


class RetrievalRequest(Question):
    entities: list[str] = Field(default_factory=list, max_length=8)

    @field_validator('entities')
    @classmethod
    def validate_entities(cls, values):
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError('Invalid entity.')
        return list(dict.fromkeys(v.strip() for v in values))


class SubgraphRequest(BaseModel):
    start_id: str = Field(min_length=1, max_length=100)
    end_id: str | None = Field(default=None, max_length=100)
    target_types: list[str] = Field(default_factory=list, max_length=10)
    relationship_types: list[str] = Field(default_factory=list, max_length=100)
    min_confidence: float = Field(default=0, ge=0, le=1)
    hops: int = Field(default=2, ge=1, le=3)
    limit: int = Field(default=50, ge=1, le=200)
