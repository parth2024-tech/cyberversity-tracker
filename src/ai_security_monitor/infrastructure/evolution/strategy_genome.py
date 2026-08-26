"""
Strategy Genome Module for the AI Security Monitor.

Implements the "Strategy Genome" from the 0.1% plan — representing workflows as
evolvable genomes that can be mutated, benchmarked, and selected.
This is the "Slow Loop" - Evolutionary Optimization.
"""

import json
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4, UUID

from src.database import Database


class StrategyComponent(Enum):
    """Components of a strategy that can be mutated."""
    PLANNER_MODEL = "planner_model"
    VERIFIER_MODEL = "verifier_model"
    MAX_RETRIES = "max_retries"
    SEARCH_FIRST = "search_first"
    PARALLEL_AGENTS = "parallel_agents"
    LOCAL_OR_REMOTE = "local_or_remote"
    VERIFICATION_THRESHOLD = "verification_threshold"
    BLAST_RADIUS_WEIGHT = "blast_radius_weight"
    VELOCITY_WEIGHT = "velocity_weight"
    SEVERITY_WEIGHT = "severity_weight"
    PRE_CVE_BOOST = "pre_cve_boost"
    WEAPONIZATION_WEIGHT = "weaponization_weight"


@dataclass
class StrategyDna:
    """
    Represents a complete strategy as a genome.
    Each gene is a configurable parameter of the analysis pipeline.
    """
    genes: Dict[str, Any] = field(default_factory=dict)
    generation: int = 0
    parent_ids: List[UUID] = field(default_factory=list)
    fitness_score: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    id: UUID = field(default_factory=uuid4)
    
    # Default genome template
    DEFAULT_GENES = {
        "planner_model": "heuristic:v2.1",
        "verifier_model": "heuristic:v2.1", 
        "max_retries": 2,
        "search_first": True,
        "parallel_agents": 2,
        "local_or_remote": "local",
        "verification_threshold": 0.85,
        "blast_radius_weight": 0.3,
        "velocity_weight": 0.4,
        "severity_weight": 0.3,
        "pre_cve_boost": 15,
        "weaponization_weight": 0.25,
    }
    
    def __post_init__(self):
        """Fill in missing genes with defaults."""
        for key, default_val in self.DEFAULT_GENES.items():
            if key not in self.genes:
                self.genes[key] = default_val
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a gene value."""
        return self.genes.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a gene value."""
        self.genes[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": str(self.id),
            "genes": self.genes,
            "generation": self.generation,
            "parent_ids": [str(p) for p in self.parent_ids],
            "fitness_score": self.fitness_score,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyDna":
        """Deserialize from dictionary."""
        dna = cls(
            genes=data["genes"],
            generation=data["generation"],
            parent_ids=[UUID(p) for p in data.get("parent_ids", [])],
            fitness_score=data.get("fitness_score", 0.0),
            created_at=data.get("created_at", datetime.now().isoformat()),
            id=UUID(data["id"]),
        )
        return dna
    
    def mutate(self, mutation_rate: float = 0.3, mutation_strength: float = 0.2) -> "StrategyDna":
        """Create a mutated offspring."""
        new_genes = self.genes.copy()
        
        for key, value in self.DEFAULT_GENES.items():
            if random.random() < mutation_rate:
                if isinstance(value, bool):
                    new_genes[key] = not value
                elif isinstance(value, int):
                    # Mutate integer within reasonable bounds
                    if key == "max_retries":
                        new_genes[key] = max(0, min(5, value + random.randint(-1, 1)))
                    elif key == "parallel_agents":
                        new_genes[key] = max(1, min(5, value + random.randint(-1, 1)))
                    elif key == "pre_cve_boost":
                        new_genes[key] = max(0, min(50, value + random.randint(-10, 10)))
                elif isinstance(value, float):
                    # Mutate float within bounds
                    if "weight" in key or "threshold" in key:
                        new_genes[key] = max(0.0, min(1.0, value + random.uniform(-mutation_strength, mutation_strength)))
                    elif key == "verification_threshold":
                        new_genes[key] = max(0.5, min(0.99, value + random.uniform(-mutation_strength, mutation_strength)))
                elif isinstance(value, str):
                    # Mutate model selection
                    if "model" in key:
                        models = ["heuristic:v2.1", "ollama:llama3.2:3b", "ollama:mistral:7b", "groq:llama-3.1-8b-instant"]
                        new_genes[key] = random.choice(models)
                    elif key == "local_or_remote":
                        new_genes[key] = random.choice(["local", "remote", "dynamic"])
        
        return StrategyDna(
            genes=new_genes,
            generation=self.generation + 1,
            parent_ids=[self.id],
        )
    
    def crossover(self, other: "StrategyDna") -> "StrategyDna":
        """Create offspring via crossover with another strategy."""
        new_genes = {}
        for key in self.DEFAULT_GENES:
            new_genes[key] = self.genes[key] if random.random() < 0.5 else other.genes.get(key, self.DEFAULT_GENES[key])
        
        return StrategyDna(
            genes=new_genes,
            generation=max(self.generation, other.generation) + 1,
            parent_ids=[self.id, other.id],
        )


@dataclass
class BenchmarkResult:
    """Result of benchmarking a strategy against a test set."""
    strategy_id: UUID
    strategy_genes: Dict[str, Any]
    test_entries: int
    metrics: Dict[str, float]  # e.g., {"accuracy": 0.85, "latency_ms": 245, "cost": 0.02}
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def composite_score(self, weights: Dict[str, float] = None) -> float:
        """Calculate weighted composite fitness score."""
        if weights is None:
            weights = {
                "accuracy": 0.5,
                "latency_ms": -0.2,  # Negative weight = lower is better
                "cost": -0.2,         # Negative weight = lower is better
                "high_velocity_capture": 0.1,
            }
        
        score = 0.0
        for metric, weight in weights.items():
            if metric in self.metrics:
                score += weight * self.metrics[metric]
        return score


class Mutator:
    """Evolutionary mutation operator for strategy genomes."""
    
    def __init__(self, mutation_rate: float = 0.3, mutation_strength: float = 0.2):
        self.mutation_rate = mutation_rate
        self.mutation_strength = mutation_strength
    
    def mutate(self, parent: StrategyDna) -> StrategyDna:
        """Apply mutation to a parent strategy."""
        return parent.mutate(self.mutation_rate, self.mutation_strength)
    
    def mutate_batch(self, parents: List[StrategyDna], offspring_per_parent: int = 2) -> List[StrategyDna]:
        """Generate multiple offspring from parents."""
        offspring = []
        for parent in parents:
            for _ in range(offspring_per_parent):
                offspring.append(self.mutate(parent))
        return offspring


class BenchmarkRunner:
    """
    Runs benchmarks of strategies against historical test data.
    Uses the existing database entries as test cases.
    """
    
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
    
    def run_benchmark(
        self, 
        strategy: StrategyDna, 
        test_limit: int = 100,
        test_since_days: int = 7,
        analyzer_fn: Optional[Callable] = None
    ) -> BenchmarkResult:
        """
        Benchmark a strategy against historical entries.
        
        Args:
            strategy: StrategyDna to test
            test_limit: Maximum number of test entries
            test_since_days: How far back to pull test entries
            analyzer_fn: Function that runs analysis with given strategy genes
            
        Returns:
            BenchmarkResult with metrics
        """
        # Import here to avoid circular dependency
        from src.analyzer import create_heuristic_analyzer
        
        if analyzer_fn is None:
            # Default: use heuristic analyzer with strategy parameters
            def default_analyzer(entry: Dict, genes: Dict) -> Tuple[int, Any]:
                analyzer = create_heuristic_analyzer({"strategy_genes": genes})
                result = analyzer.analyze(entry)
                return entry['id'], result
            analyzer_fn = default_analyzer
        
        # Get test entries from database
        from datetime import timedelta
        since = datetime.now() - timedelta(days=test_since_days)
        test_entries = self.db.get_entries(since=since, limit=test_limit)
        
        if not test_entries:
            return BenchmarkResult(
                strategy_id=strategy.id,
                strategy_genes=strategy.genes,
                test_entries=0,
                metrics={"accuracy": 0.0, "latency_ms": 0.0, "cost": 0.0}
            )
        
        # Run analysis with this strategy
        import time
        start_time = time.time()
        results = []
        high_vel_captured = 0
        
        for entry in test_entries:
            try:
                entry_id, analysis = analyzer_fn(entry, strategy.genes)
                results.append((entry_id, analysis))
                if analysis.threat_velocity >= 70:
                    high_vel_captured += 1
            except Exception as e:
                print(f"Benchmark error for entry {entry.get('id')}: {e}")
        
        total_latency = (time.time() - start_time) * 1000
        avg_latency = total_latency / len(results) if results else 0
        
        # Calculate accuracy proxy: how well does threat_velocity predict actual severity?
        # This is a simplified metric - in practice you'd compare against ground truth
        accuracy = high_vel_captured / len(test_entries) if test_entries else 0
        
        return BenchmarkResult(
            strategy_id=strategy.id,
            strategy_genes=strategy.genes,
            test_entries=len(test_entries),
            metrics={
                "accuracy": accuracy,
                "latency_ms": avg_latency,
                "cost": 0.0,  # Heuristic is free
                "high_velocity_capture": high_vel_captured / len(test_entries) if test_entries else 0,
            }
        )
    
    def run_tournament(
        self,
        strategies: List[StrategyDna],
        test_limit: int = 100,
        analyzer_fn: Optional[Callable] = None
    ) -> List[Tuple[StrategyDna, BenchmarkResult]]:
        """Run a tournament: benchmark all strategies and return sorted by fitness."""
        results = []
        for strategy in strategies:
            result = self.run_benchmark(strategy, test_limit=test_limit, analyzer_fn=analyzer_fn)
            strategy.fitness_score = result.composite_score()
            results.append((strategy, result))
        
        # Sort by fitness (descending)
        results.sort(key=lambda x: x[0].fitness_score, reverse=True)
        return results


class EvolutionEngine:
    """
    Main evolution engine that manages the strategy population,
    runs generations, and selects winners.
    """
    
    def __init__(self, db: Database, population_size: int = 20):
        self.db = db
        self.population_size = population_size
        self.mutator = Mutator()
        self.benchmark_runner = BenchmarkRunner(db)
        self._lock = threading.Lock()
        self.population: List[StrategyDna] = []
        self.generation = 0
        self.history: List[Dict] = []  # Generation history
    
    def initialize_population(self, seed_strategies: Optional[List[StrategyDna]] = None) -> List[StrategyDna]:
        """Initialize the population with seed strategies or random ones."""
        if seed_strategies:
            self.population = seed_strategies[:self.population_size]
        else:
            # Create diverse random strategies
            self.population = []
            for _ in range(self.population_size):
                base = StrategyDna()
                # Add some initial diversity
                mutated = base.mutate(mutation_rate=0.5, mutation_strength=0.3)
                self.population.append(mutated)
        return self.population
    
    def run_generation(
        self, 
        test_limit: int = 100,
        elite_size: int = 3,
        analyzer_fn: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Run one evolutionary generation."""
        with self._lock:
            # Benchmark current population
            tournament_results = self.benchmark_runner.run_tournament(
                self.population, test_limit=test_limit, analyzer_fn=analyzer_fn
            )
            
            # Select elites
            elites = [strategy for strategy, _ in tournament_results[:elite_size]]
            
            # Generate offspring from elites
            offspring = self.mutator.mutate_batch(elites, offspring_per_parent=3)
            
            # Add some random immigrants for diversity
            immigrants = [StrategyDna().mutate(mutation_rate=0.5) for _ in range(2)]
            
            # New population = elites + offspring + immigrants (trimmed to population_size)
            new_population = elites + offspring + immigrants
            new_population = new_population[:self.population_size]
            
            self.population = new_population
            self.generation += 1
            
            # Record history
            gen_record = {
                "generation": self.generation,
                "best_fitness": tournament_results[0][0].fitness_score,
                "avg_fitness": sum(s.fitness_score for s, _ in tournament_results) / len(tournament_results),
                "best_strategy_genes": tournament_results[0][0].genes,
                "population_size": len(self.population),
                "timestamp": datetime.now().isoformat(),
            }
            self.history.append(gen_record)
            
            return gen_record
    
    def get_best_strategy(self) -> Optional[StrategyDna]:
        """Get the current best strategy."""
        if not self.population:
            return None
        return max(self.population, key=lambda s: s.fitness_score)
    
    def save_best_strategy(self, name: str = "best") -> bool:
        """Save the best strategy to database for production use."""
        best = self.get_best_strategy()
        if not best:
            return False
        
        with self._lock:
            with self.db.transaction() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_genome (
                        name TEXT PRIMARY KEY,
                        genes TEXT NOT NULL,
                        generation INTEGER,
                        fitness_score REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    INSERT OR REPLACE INTO strategy_genome (name, genes, generation, fitness_score)
                    VALUES (?, ?, ?, ?)
                """, (name, json.dumps(best.genes), best.generation, best.fitness_score))
        return True
    
    def load_strategy(self, name: str = "best") -> Optional[StrategyDna]:
        """Load a saved strategy from database."""
        with self._lock:
            with self.db.transaction() as conn:
                row = conn.execute("SELECT * FROM strategy_genome WHERE name = ?", (name,)).fetchone()
                if row:
                    return StrategyDna.from_dict({
                        "id": uuid4(),
                        "genes": json.loads(row['genes']),
                        "generation": row['generation'],
                        "parent_ids": [],
                        "fitness_score": row['fitness_score'],
                        "created_at": row['created_at'],
                    })
        return None


def create_evolution_engine(db: Database, population_size: int = 20) -> EvolutionEngine:
    """Factory function to create an evolution engine."""
    return EvolutionEngine(db, population_size)
