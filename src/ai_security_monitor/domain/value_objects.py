"""
Value objects - immutable domain objects with value equality.
"""

from dataclasses import dataclass
from typing import Self
import hashlib


@dataclass(frozen=True, slots=True)
class ContentHash:
    """SHA256 content hash for deduplication."""
    value: str

    def __post_init__(self):
        if not self.value:
            raise ValueError("Content hash cannot be empty")
        if len(self.value) != 64:  # SHA256 hex = 64 chars
            raise ValueError("Content hash must be 64 character hex string")

    @classmethod
    def from_content(cls, *parts: str) -> Self:
        """Create hash from content parts."""
        content = "|".join(str(p) for p in parts if p)
        hash_value = hashlib.sha256(content.encode()).hexdigest()
        return cls(value=hash_value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ThreatScore:
    """Threat scoring value object (1-100)."""
    velocity: int  # 1-100: How fast threat is moving
    severity: int  # 1-100: How severe the impact
    blast_radius: int = 0  # 1-100: Ecosystem impact

    def __post_init__(self):
        for field_name in ("velocity", "severity", "blast_radius"):
            value = getattr(self, field_name)
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be 0-100, got {value}")

    @property
    def is_high_velocity(self) -> bool:
        return self.velocity >= 70

    @property
    def is_critical(self) -> bool:
        return self.velocity >= 80 and self.severity >= 70

    def __str__(self) -> str:
        return f"V:{self.velocity} S:{self.severity} B:{self.blast_radius}"


@dataclass(frozen=True, slots=True)
class WeaponizationLevel:
    """Weaponization potential level."""
    THEORETICAL = "Theoretical"
    POC_VERIFIED = "PoC Verified"
    ACTIVE_WEAPONIZATION = "Active Weaponization"

    value: str

    def __post_init__(self):
        valid = {self.THEORETICAL, self.POC_VERIFIED, self.ACTIVE_WEAPONIZATION}
        if self.value not in valid:
            raise ValueError(f"Invalid weaponization level: {self.value}")

    @classmethod
    def theoretical(cls) -> Self:
        return cls(cls.THEORETICAL)

    @classmethod
    def poc_verified(cls) -> Self:
        return cls(cls.POC_VERIFIED)

    @classmethod
    def active_weaponization(cls) -> Self:
        return cls(cls.ACTIVE_WEAPONIZATION)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AttackArchetype:
    """Known attack archetypes for classification."""
    JAILBREAK = "Jailbreak"
    RAG_POISONING = "RAG Poisoning"
    MODEL_INVERSION = "Model Inversion"
    PROMPT_INJECTION = "Prompt Injection"
    DATA_POISONING = "Data Poisoning"
    MODEL_EXTRACTION = "Model Extraction"
    SUPPLY_CHAIN = "Supply Chain Compromise"
    RCE = "Remote Code Execution"
    PRIVILEGE_ESCALATION = "Privilege Escalation"
    NOVEL_ACADEMIC = "Novel Academic Threat Vector"
    STANDARD_VULN = "Standard Vulnerability"
    UNKNOWN = "Unknown"

    value: str

    def __post_init__(self):
        valid = {
            self.JAILBREAK, self.RAG_POISONING, self.MODEL_INVERSION,
            self.PROMPT_INJECTION, self.DATA_POISONING, self.MODEL_EXTRACTION,
            self.SUPPLY_CHAIN, self.RCE, self.PRIVILEGE_ESCALATION,
            self.NOVEL_ACADEMIC, self.STANDARD_VULN, self.UNKNOWN
        }
        if self.value not in valid:
            raise ValueError(f"Invalid attack archetype: {self.value}")

    @classmethod
    def from_string(cls, value: str) -> Self:
        """Create from string, defaulting to UNKNOWN."""
        try:
            return cls(value)
        except ValueError:
            return cls(cls.UNKNOWN)

    def __str__(self) -> str:
        return self.value