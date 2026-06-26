"""
Main knowledge management system for Agent Byte.

This module coordinates all knowledge components and provides a unified
interface for knowledge operations across the dual brain system.
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import logging
import time

from .pattern_interpreter import PatternInterpreter
from .skill_discovery import SkillDiscovery
from .decision_maker import SymbolicDecisionMaker
from .transfer_mapper import TransferMapper


class KnowledgeSystem:
    """
    Unified knowledge management system for Agent Byte.

    This system coordinates:
    - Pattern interpretation from neural insights
    - Skill discovery and management
    - Symbolic decision-making
    - Knowledge transfer between environments
    """

    def __init__(self):
        """Initialize the knowledge system."""
        self.logger = logging.getLogger(self.__class__.__name__)

        # Core components
        self.pattern_interpreter = PatternInterpreter()
        self.skill_discovery = SkillDiscovery()
        self.decision_maker = SymbolicDecisionMaker()
        self.transfer_mapper = TransferMapper()

        # Knowledge state
        self.current_environment = None
        self.knowledge_base = {
            'environments': {},
            'universal_skills': {},
            'transfer_history': [],
            'meta_knowledge': {
                'total_environments': 0,
                'total_skills_discovered': 0,
                'successful_transfers': 0,
                'knowledge_creation_time': time.time()
            }
        }

        self.logger.info("Knowledge system initialized")

    def process_neural_insights(self, env_id: str, neural_insights: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process neural insights to extract symbolic knowledge.

        Args:
            env_id: Environment identifier
            neural_insights: Insights from neural brain

        Returns:
            Processed knowledge including patterns, skills, and recommendations
        """
        self.current_environment = env_id

        # Ensure environment exists in knowledge base
        if env_id not in self.knowledge_base['environments']:
            self._initialize_environment_knowledge(env_id)

        env_knowledge = self.knowledge_base['environments'][env_id]

        # Step 1: Interpret patterns
        pattern_interpretation = self.pattern_interpreter.interpret(neural_insights)
        env_knowledge['pattern_history'].append({
            'timestamp': time.time(),
            'interpretation': pattern_interpretation
        })

        # Keep pattern history bounded
        if len(env_knowledge['pattern_history']) > 100:
            env_knowledge['pattern_history'] = env_knowledge['pattern_history'][-100:]

        # Step 2: Discover skills
        discovered_skills = self.skill_discovery.discover(
            pattern_interpretation,
            env_knowledge['discovered_skills']
        )

        # Add discovered skills to environment knowledge
        for skill in discovered_skills:
            skill_id = skill['id']
            env_knowledge['discovered_skills'][skill_id] = {
                'skill': skill,
                'discovered_at': time.time(),
                'application_count': 0,
                'success_rate': 0.0,
                'confidence': skill.get('confidence', 0.5)
            }

            # Check if skill is universal
            if skill.get('abstraction_level') in ['strategic', 'meta']:
                self._add_universal_skill(skill)

        # Step 3: Update meta-knowledge
        self.knowledge_base['meta_knowledge']['total_skills_discovered'] += len(discovered_skills)

        # Step 4: Analyze skill relationships
        skill_relationships = self.skill_discovery.analyze_skill_relationships(
            env_knowledge['discovered_skills']
        )

        return {
            'pattern_interpretation': pattern_interpretation,
            'discovered_skills': discovered_skills,
            'skill_relationships': skill_relationships,
            'total_skills': len(env_knowledge['discovered_skills']),
            'recommendations': self._generate_recommendations(env_id, pattern_interpretation)
        }

    def make_decision(self, env_id: str, state: np.ndarray, q_values: np.ndarray,
                      exploration_rate: float) -> Tuple[Optional[int], str, float]:
        """
        Make a symbolic decision based on current knowledge.

        Args:
            env_id: Environment identifier
            state: Current state
            q_values: Q-values from neural network
            exploration_rate: Current exploration rate

        Returns:
            Tuple of (action, reasoning, confidence)
        """
        if env_id not in self.knowledge_base['environments']:
            return None, "No knowledge for this environment", 0.0

        env_knowledge = self.knowledge_base['environments'][env_id]

        # Prepare context for decision maker
        context = {
            'state': state,
            'q_values': q_values,
            'exploration_rate': exploration_rate,
            'discovered_skills': env_knowledge['discovered_skills'],
            'recent_patterns': [p['interpretation'] for p in env_knowledge['pattern_history'][-5:]],
            'environment_analysis': env_knowledge.get('environment_analysis')
        }

        # Make a decision
        action, reasoning, confidence = self.decision_maker.decide(context)

        # Record decision
        env_knowledge['decision_history'].append({
            'timestamp': time.time(),
            'action': action,
            'reasoning': reasoning,
            'confidence': confidence
        })

        # Keep decision history bounded
        if len(env_knowledge['decision_history']) > 100:
            env_knowledge['decision_history'] = env_knowledge['decision_history'][-100:]

        return action, reasoning, confidence



    def update_skill_outcome(self, env_id: str, skill_id: str, success: bool, reward: float):
        """
        Update the outcome of a skill application.

        Args:
            env_id: Environment identifier
            skill_id: Skill that was applied
            success: Whether application was successful
            reward: Reward received
        """
        if env_id not in self.knowledge_base['environments']:
            return

        env_knowledge = self.knowledge_base['environments'][env_id]

        if skill_id in env_knowledge['discovered_skills']:
            skill_data = env_knowledge['discovered_skills'][skill_id]
            skill_data['application_count'] += 1

            # Update success rate with exponential moving average
            alpha = 0.1
            current_rate = skill_data['success_rate']
            skill_data['success_rate'] = (1 - alpha) * current_rate + alpha * (1.0 if success else 0.0)

            # Update confidence
            if success and reward > 0:
                skill_data['confidence'] = min(1.0, skill_data['confidence'] * 1.1)
            elif not success:
                skill_data['confidence'] = max(0.1, skill_data['confidence'] * 0.9)

    def prepare_transfer_package(self, source_env: str) -> Dict[str, Any]:
        """
        Prepare knowledge for transfer to another environment.

        Args:
            source_env: Source environment ID

        Returns:
            Transfer package containing transferable knowledge
        """
        if source_env not in self.knowledge_base['environments']:
            return {'error': 'Source environment not found'}

        env_knowledge = self.knowledge_base['environments'][source_env]

        # Filter transferable skills
        transferable_skills = {}
        for skill_id, skill_data in env_knowledge['discovered_skills'].items():
            if skill_data['confidence'] > 0.6 and skill_data['success_rate'] > 0.5:
                transferable_skills[skill_id] = skill_data

        # Include universal skills
        universal_skills = self.knowledge_base['universal_skills']

        # Prepare pattern summary
        pattern_summary = self._summarize_patterns(env_knowledge['pattern_history'])

        return {
            'source_environment': source_env,
            'transferable_skills': transferable_skills,
            'universal_skills': universal_skills,
            'pattern_summary': pattern_summary,
            'environment_type': env_knowledge.get('environment_type', 'unknown'),
            'meta_knowledge': {
                'total_decisions': len(env_knowledge['decision_history']),
                'avg_confidence': np.mean([d['confidence'] for d in env_knowledge['decision_history']]) if
                env_knowledge['decision_history'] else 0.0
            }
        }

    def apply_transfer(self, target_env: str, transfer_package: Dict[str, Any],
                       target_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply transferred knowledge to a new environment with validation pipeline.

        Args:
            target_env: Target environment ID
            transfer_package: Knowledge package from source
            target_analysis: Analysis of target environment

        Returns:
            Transfer results
        """
        # Ensure target environment exists
        if target_env not in self.knowledge_base['environments']:
            self._initialize_environment_knowledge(target_env)

        # Use transfer mapper to adapt knowledge
        mapped_knowledge = self.transfer_mapper.map_knowledge(
            transfer_package, target_analysis
        )

        # NEW: Add validation tracking BEFORE applying skills
        validation_context = {
            'pre_transfer_performance': self._get_baseline_performance(target_env),
            'transferred_skills': mapped_knowledge['transferable_skills'],
            'transfer_timestamp': time.time(),
            'source_environment': transfer_package.get('source_environment', 'unknown')
        }

        # Apply mapped knowledge to target environment
        target_knowledge = self.knowledge_base['environments'][target_env]

        # Add transferred skills
        for skill_id, skill_data in mapped_knowledge['transferable_skills'].items():
            if skill_id not in target_knowledge['discovered_skills']:
                target_knowledge['discovered_skills'][skill_id] = skill_data
                self.logger.info(f"Transferred skill {skill_data['skill']['name']} to {target_env}")

        # Update environment analysis
        if 'environment_analysis' in target_analysis:
            target_knowledge['environment_analysis'] = target_analysis

        # Store validation context for later validation
        target_knowledge['pending_validation'] = validation_context

        # Record transfer
        transfer_record = {
            'source': transfer_package.get('source_environment', 'unknown'),
            'target': target_env,
            'timestamp': time.time(),
            'skills_transferred': len(mapped_knowledge['transferable_skills']),
            'confidence': mapped_knowledge['transfer_confidence']
        }

        self.knowledge_base['transfer_history'].append(transfer_record)

        # Update meta-knowledge
        if mapped_knowledge['transfer_confidence'] > 0.5:
            self.knowledge_base['meta_knowledge']['successful_transfers'] += 1

        return mapped_knowledge

    def get_knowledge_summary(self, env_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get summary of knowledge system state.

        Args:
            env_id: Specific environment or None for global summary

        Returns:
            Knowledge summary
        """
        if env_id:
            if env_id not in self.knowledge_base['environments']:
                return {'error': 'Environment not found'}

            env_knowledge = self.knowledge_base['environments'][env_id]

            # Get top skills
            top_skills = sorted(
                env_knowledge['discovered_skills'].items(),
                key=lambda x: x[1]['confidence'] * x[1]['success_rate'],
                reverse=True
            )[:5]

            return {
                'environment': env_id,
                'total_skills': len(env_knowledge['discovered_skills']),
                'top_skills': [
                    {
                        'name': skill_data['skill']['name'],
                        'type': skill_data['skill']['type'],
                        'confidence': skill_data['confidence'],
                        'success_rate': skill_data['success_rate'],
                        'applications': skill_data['application_count']
                    }
                    for _, skill_data in top_skills
                ],
                'total_decisions': len(env_knowledge['decision_history']),
                'pattern_stability': self._calculate_pattern_stability(env_knowledge['pattern_history']),
                'environment_type': env_knowledge.get('environment_type', 'unknown')
            }
        else:
            # Global summary
            return {
                'total_environments': len(self.knowledge_base['environments']),
                'total_skills_discovered': self.knowledge_base['meta_knowledge']['total_skills_discovered'],
                'universal_skills': len(self.knowledge_base['universal_skills']),
                'successful_transfers': self.knowledge_base['meta_knowledge']['successful_transfers'],
                'total_transfers': len(self.knowledge_base['transfer_history']),
                'environments': list(self.knowledge_base['environments'].keys())
            }

    def _initialize_environment_knowledge(self, env_id: str):
        """Initialize knowledge structure for a new environment."""
        self.knowledge_base['environments'][env_id] = {
            'discovered_skills': {},
            'pattern_history': [],
            'decision_history': [],
            'environment_analysis': None,
            'environment_type': 'unknown',
            'created_at': time.time()
        }

        self.knowledge_base['meta_knowledge']['total_environments'] += 1
        self.logger.info(f"Initialized knowledge for environment: {env_id}")

    def _add_universal_skill(self, skill: Dict[str, Any]):
        """Add a skill to universal skills if it's abstract enough."""
        skill_id = skill['id']

        if skill_id not in self.knowledge_base['universal_skills']:
            self.knowledge_base['universal_skills'][skill_id] = {
                'skill': skill,
                'discovered_at': time.time(),
                'applied_environments': [self.current_environment],
                'universal_confidence': skill.get('confidence', 0.5)
            }
            self.logger.info(f"Added universal skill: {skill['name']}")
        else:
            # Update environments where it's been applied
            universal_skill = self.knowledge_base['universal_skills'][skill_id]
            if self.current_environment not in universal_skill['applied_environments']:
                universal_skill['applied_environments'].append(self.current_environment)

    def _generate_recommendations(self, env_id: str, interpretation: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on current knowledge state."""
        recommendations = []

        env_knowledge = self.knowledge_base['environments'][env_id]

        # Based on skill count
        skill_count = len(env_knowledge['discovered_skills'])
        if skill_count < 3:
            recommendations.append("Continue exploration to discover more skills")
        elif skill_count > 10:
            recommendations.append("Focus on refining high-confidence skills")

        # Based on pattern interpretation
        recommendations.extend(interpretation.get('recommendations', []))

        # Based on transfer potential
        if skill_count > 5 and any(
                skill_data['confidence'] > 0.8
                for skill_data in env_knowledge['discovered_skills'].values()
        ):
            recommendations.append("High-confidence skills ready for transfer to other environments")

        return recommendations

    def _summarize_patterns(self, pattern_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize pattern history for transfer."""
        if not pattern_history:
            return {'status': 'no_patterns'}

        recent_patterns = pattern_history[-20:]

        # Extract behavioral states
        behavioral_states = [p['interpretation']['behavioral_state'] for p in recent_patterns]
        state_counts = {}
        for state in behavioral_states:
            state_counts[state] = state_counts.get(state, 0) + 1

        # Extract learning phases
        learning_phases = [p['interpretation']['learning_phase'] for p in recent_patterns]
        phase_counts = {}
        for phase in learning_phases:
            phase_counts[phase] = phase_counts.get(phase, 0) + 1

        return {
            'dominant_behavioral_state': max(state_counts, key=state_counts.get) if state_counts else 'unknown',
            'dominant_learning_phase': max(phase_counts, key=phase_counts.get) if phase_counts else 'unknown',
            'pattern_diversity': len(set(behavioral_states)) / len(behavioral_states) if behavioral_states else 0,
            'average_confidence': np.mean([p['interpretation']['confidence'] for p in recent_patterns])
        }

    def _calculate_pattern_stability(self, pattern_history: List[Dict[str, Any]]) -> float:
        """Calculate the stability of behavioral patterns."""
        if len(pattern_history) < 5:
            return 0.0

        recent_patterns = pattern_history[-10:]
        behavioral_states = [p['interpretation']['behavioral_state'] for p in recent_patterns]

        # Calculate consistency
        state_changes = sum(1 for i in range(1, len(behavioral_states))
                            if behavioral_states[i] != behavioral_states[i - 1])

        stability = 1.0 - (state_changes / (len(behavioral_states) - 1))
        return stability

    def validate_active_transfers(self, env_id: str, current_performance: Dict[str, Any]):
        """Validate any pending transfers for this environment."""
        if env_id not in self.knowledge_base['environments']:
            return None

        env_knowledge = self.knowledge_base['environments'][env_id]

        if 'pending_validation' not in env_knowledge:
            return None

        validation_context = env_knowledge['pending_validation']

        # Use existing skill performance data
        transferred_skills = validation_context['transferred_skills']
        validated_skills = {}

        for skill_id in transferred_skills:
            if skill_id in env_knowledge['discovered_skills']:
                skill_data = env_knowledge['discovered_skills'][skill_id]
                validated_skills[skill_id] = skill_data

        if not validated_skills:
            return None

        # Perform validation using transfer_mapper (which you already have!)
        source_env = validation_context.get('source_environment', 'unknown')
        validation_result = self.transfer_mapper.validate_transfer(
            source_env, env_id, validated_skills, current_performance
        )

        # Remove from pending if validation complete
        if validation_result and validation_result.get('overall_success', False):
            del env_knowledge['pending_validation']
            self.logger.info(f"Transfer validation successful for {env_id}")
        elif validation_result:
            # Keep pending but log the result
            self.logger.info(
                f"Transfer validation ongoing for {env_id}: {validation_result.get('performance_delta', 0)}")

        return validation_result

    def get_transfer_validation_report(self, env_id: str) -> Dict[str, Any]:
        """Get detailed report on transfer validation results."""
        env_pair_metrics = {}

        # Collect metrics for all transfers involving this environment as target
        for env_pair, metrics in self.transfer_mapper.transfer_success_metrics.items():
            if env_pair.endswith(f"->{env_id}"):
                env_pair_metrics[env_pair] = metrics

        report = {
            'target_environment': env_id,
            'transfer_metrics': env_pair_metrics,
            'total_transfers_to_env': len(env_pair_metrics),
            'validation_history': self.transfer_mapper.validation_metrics.get(env_id, {})
        }

        # Calculate average improvement if we have data
        improvements = []
        for metrics in env_pair_metrics.values():
            if 'average_improvement' in metrics:
                improvements.append(metrics['average_improvement'])

        if improvements:
            report['average_improvement'] = np.mean(improvements)
            report['best_transfer_source'] = max(env_pair_metrics.keys(),
                                                 key=lambda k: env_pair_metrics[k].get('average_improvement', 0))
        else:
            report['average_improvement'] = 0
            report['best_transfer_source'] = None

        return report

    def _get_baseline_performance(self, env_id: str) -> Dict[str, Any]:
        """Get baseline performance metrics for comparison."""
        if env_id not in self.knowledge_base['environments']:
            return {'average_reward': 0, 'step_count': 0, 'timestamp': time.time()}

        env_knowledge = self.knowledge_base['environments'][env_id]
        decision_history = env_knowledge.get('decision_history', [])

        if not decision_history:
            return {'average_reward': 0, 'step_count': 0, 'timestamp': time.time()}

        # Calculate baseline from recent decisions
        recent_decisions = decision_history[-50:]  # Last 50 decisions
        avg_confidence = np.mean([d['confidence'] for d in recent_decisions])

        return {
            'average_reward': avg_confidence,  # Use confidence as proxy for performance
            'step_count': len(decision_history),
            'recent_confidence': avg_confidence,
            'total_decisions': len(decision_history),
            'timestamp': time.time()
        }