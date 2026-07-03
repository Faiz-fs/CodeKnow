"""Analysis configuration with configurable thresholds for contributor and decay analysis."""

from typing import Any, Dict

from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic import Field


@pydantic_dataclass
class AnalysisConfig:
    """Configuration for contributor analysis and decay detection."""

    max_commits: int = Field(default=500, ge=10, le=5000)
    decay_warning_days: int = Field(default=60, ge=7, le=365)
    decay_critical_days: int = Field(default=90, ge=14, le=730)
    decay_critical_commits: int = Field(default=3, ge=1, le=50)
    decay_critical_change_pct: float = Field(default=30.0, ge=5.0, le=100.0)
    bus_factor_threshold: float = Field(default=0.50, ge=0.1, le=0.9)

    def __post_init__(self) -> None:
        """Validate configuration consistency after initialization."""
        if self.decay_critical_days <= self.decay_warning_days:
            raise ValueError(
                f"decay_critical_days ({self.decay_critical_days}) must be greater than decay_warning_days ({self.decay_warning_days})"
            )

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "AnalysisConfig":
        """Create AnalysisConfig from dictionary with partial values."""
        defaults = {
            "max_commits": 500,
            "decay_warning_days": 60,
            "decay_critical_days": 90,
            "decay_critical_commits": 3,
            "decay_critical_change_pct": 30.0,
            "bus_factor_threshold": 0.50,
        }
        merged = {**defaults, **config_dict}
        return cls(**merged)

    def to_dict(self) -> Dict[str, Any]:
        """Convert AnalysisConfig to dictionary for serialization."""
        return {
            "max_commits": self.max_commits,
            "decay_warning_days": self.decay_warning_days,
            "decay_critical_days": self.decay_critical_days,
            "decay_critical_commits": self.decay_critical_commits,
            "decay_critical_change_pct": self.decay_critical_change_pct,
            "bus_factor_threshold": self.bus_factor_threshold,
        }

    def __str__(self) -> str:
        """String representation showing key configuration values."""
        return (f"AnalysisConfig(max_commits={self.max_commits}, "
                f"decay_warning_days={self.decay_warning_days}, "
                f"decay_critical_days={self.decay_critical_days}, "
                f"decay_critical_commits={self.decay_critical_commits}, "
                f"decay_critical_change_pct={self.decay_critical_change_pct}, "
                f"bus_factor_threshold={self.bus_factor_threshold})")