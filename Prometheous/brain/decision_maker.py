"""
Symbolic decision maker for Agent Byte.

This module makes high-level decisions based on discovered skills and
current context, without any hard-coded environment knowledge.
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple, List
import logging


class SymbolicDecisionMaker:
    """
    Makes symbolic decisions based on learned skills and context.

    This decision maker selects actions based on high-level reasoning
    about discovered skills, current patterns, and environmental understanding.
    """

    def __init__(self):
        """Initialize the symbolic decision maker."""
        self.logger = logging.getLogger(self.__class__.__name__)

        # Decision strategies
        self.strategies = {
            'skill_based': self._skill_based_decision,
            'pattern_based': self._pattern_based_decision,
            'exploration_based': self._exploration_based_decision,
            'confidence_based': self._confidence_based_decision,
            'meta_strategy': self._meta_strategy_decision
        }

        # Decision history for learning
        self.decision_history = []
        self.max_history = 100

        # Strategy selection criteria
        self.strategy_thresholds = {
            'min_skills': 2,
            'min_patterns': 3,
            'confidence_threshold': 0.6,
            'exploration_threshold': 0.3
        }

    def decide(self, context: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        """Make a symbolic decision based on context."""
        self.context = context  # Store context for strategies

        # Extract context
        state = context.get('state', np.array([]))
        q_values = context.get('q_values', np.array([]))
        exploration_rate = context.get('exploration_rate', 1.0)
        skills = context.get('discovered_skills', {})
        patterns = context.get('recent_patterns', [])
        env_analysis = context.get('environment_analysis', {})

        # PRIORITY CHECK: Handle skill_predictions directly here (not in strategy)
        skill_predictions = context.get('skill_predictions', [])
        if skill_predictions:
            best_skill_id, best_confidence = skill_predictions[0]

            if best_skill_id in skills:
                skill_data = skills[best_skill_id]
                skill = skill_data.get('skill', {})

                # Extract action from skill
                action = self._extract_action_from_skill(skill, q_values)

                if action is not None:
                    reasoning = f"Classifier selected skill '{skill.get('name', 'unknown')}' (confidence: {best_confidence:.2f})"
                    return action, reasoning, best_confidence

        # Select decision strategy
        strategy_name, strategy_func = self._select_strategy(
            skills, patterns, exploration_rate
        )

        # Make decision using selected strategy
        action, reasoning, confidence = strategy_func(
            state, q_values, skills, patterns, env_analysis
        )

        # Record decision
        self._record_decision(strategy_name, action, reasoning, confidence)

        # Add strategy info to reasoning
        full_reasoning = f"[{strategy_name}] {reasoning}"

        return action, full_reasoning, confidence

    def _select_strategy(self, skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                         exploration_rate: float) -> Tuple[str, callable]:
        """Select appropriate decision strategy based on context."""
        # Count available resources
        active_skills = [s for s in skills.values() if s.get('confidence', 0) > 0.5]
        recent_patterns = patterns[-5:] if len(patterns) >= 5 else patterns

        # Meta-strategy if enough experience
        if len(self.decision_history) >= 20 and len(active_skills) >= 5:
            return 'meta_strategy', self.strategies['meta_strategy']

        # Skill-based if enough confident skills
        if len(active_skills) >= self.strategy_thresholds['min_skills']:
            return 'skill_based', self.strategies['skill_based']

        # Pattern-based if enough patterns
        if len(recent_patterns) >= self.strategy_thresholds['min_patterns']:
            return 'pattern_based', self.strategies['pattern_based']

        # Exploration-based if high exploration rate
        if exploration_rate > self.strategy_thresholds['exploration_threshold']:
            return 'exploration_based', self.strategies['exploration_based']

        # Default to confidence-based
        return 'confidence_based', self.strategies['confidence_based']

    def _skill_based_decision(self, state: np.ndarray, q_values: np.ndarray,
                              skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                              env_analysis: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        if not skills:
            return None, "No skills available", 0.0

        skill_predictions = self.context.get('skill_predictions', [])
        if skill_predictions:
            best_skill_id, best_confidence = skill_predictions[0]
            if best_skill_id in skills:
                skill_data = skills[best_skill_id]
                skill = skill_data.get('skill', {})
                action = self._extract_action_from_skill(skill, q_values)
                if action is not None:
                    reasoning = f"Classifier selected skill '{skill.get('name', 'unknown')}' (confidence: {best_confidence:.2f})"
                    return action, reasoning, best_confidence
                else:
                    self.logger.warning(f"Could not extract action from skill: {skill}")

        # Fallback logic (unchanged)
        applicable_skills = []
        for skill_id, skill_data in skills.items():
            skill = skill_data.get('skill', {})
            confidence = skill_data.get('confidence', 0)
            if confidence > self.strategy_thresholds['confidence_threshold']:
                if self._is_skill_applicable(skill, state, patterns):
                    applicable_skills.append({
                        'skill': skill,
                        'data': skill_data,
                        'relevance': self._calculate_skill_relevance(skill, state, patterns)
                    })

        if not applicable_skills:
            return None, "No applicable skills found", 0.0

        best_skill_info = max(applicable_skills, key=lambda x: x['relevance'] * x['data']['confidence'])
        best_skill = best_skill_info['skill']
        action = self._extract_action_from_skill(best_skill, q_values)
        if action is not None:
            confidence = best_skill_info['data']['confidence'] * best_skill_info['relevance']
            reasoning = f"Applied skill '{best_skill['name']}': {best_skill['description']}"
            return action, reasoning, confidence
        return None, "Could not extract action from skill", 0.0

    def _pattern_based_decision(self, state: np.ndarray, q_values: np.ndarray,
                                skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                                env_analysis: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        """Make decision based on recent patterns."""
        if not patterns:
            return None, "No patterns available", 0.0

        # Analyze recent patterns
        recent_patterns = patterns[-5:] if len(patterns) >= 5 else patterns

        # Look for consistent interpretations
        behavioral_states = [p.get('interpretation', {}).get('behavioral_state', 'unknown')
                             for p in recent_patterns]

        # Find dominant behavioral state
        state_counts = {}
        for bs in behavioral_states:
            state_counts[bs] = state_counts.get(bs, 0) + 1

        dominant_state = max(state_counts, key=state_counts.get)
        dominance_ratio = state_counts[dominant_state] / len(behavioral_states)

        # Make decision based on dominant state
        if dominant_state == 'stable_policy' and dominance_ratio > 0.6:
            # Follow the stable policy (trust neural network)
            action = int(np.argmax(q_values))
            reasoning = f"Following stable policy (dominance: {dominance_ratio:.2f})"
            confidence = dominance_ratio * 0.8
            return action, reasoning, confidence

        elif dominant_state == 'exploring' and dominance_ratio > 0.5:
            # Encourage exploration
            # Select action with high uncertainty (not the max Q-value)
            q_sorted = np.argsort(q_values)
            if len(q_sorted) >= 2:
                action = int(q_sorted[-2])  # Second best action
                reasoning = f"Exploring alternatives (pattern: {dominant_state})"
                confidence = 0.6
                return action, reasoning, confidence

        return None, f"No clear pattern guidance (dominant: {dominant_state})", 0.3

    def _exploration_based_decision(self, state: np.ndarray, q_values: np.ndarray,
                                    skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                                    env_analysis: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        """Make decision to encourage exploration."""
        # Analyze action distribution from environment analysis
        action_analysis = env_analysis.get('action_analysis', {})
        action_effects = action_analysis.get('action_effects', {})

        if action_effects:
            # Find least explored action
            action_frequencies = action_analysis.get('action_frequencies', {})

            if action_frequencies:
                total_actions = sum(action_frequencies.values())
                if total_actions > 0:
                    # Calculate exploration scores
                    exploration_scores = {}
                    for action in range(len(q_values)):
                        frequency = action_frequencies.get(action, 0)
                        exploration_scores[action] = 1.0 - (frequency / total_actions)

                    # Select action with highest exploration score
                    best_action = max(exploration_scores, key=exploration_scores.get)
                    confidence = exploration_scores[best_action] * 0.7

                    reasoning = f"Exploring less-visited action {best_action} (exploration score: {exploration_scores[best_action]:.2f})"
                    return best_action, reasoning, confidence

        # Default exploration: random among non-max actions
        if len(q_values) > 1:
            max_action = int(np.argmax(q_values))
            other_actions = [a for a in range(len(q_values)) if a != max_action]
            if other_actions:
                action = np.random.choice(other_actions)
                reasoning = "Random exploration of non-greedy action"
                return action, reasoning, 0.5

        return None, "Cannot determine exploration action", 0.0

    def _confidence_based_decision(self, state: np.ndarray, q_values: np.ndarray,
                                   skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                                   env_analysis: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        """Make decision based on confidence in Q-values."""
        if len(q_values) == 0:
            return None, "No Q-values available", 0.0

        # Analyze Q-value distribution
        q_mean = np.mean(q_values)
        q_std = np.std(q_values)
        q_max = np.max(q_values)
        q_max_idx = int(np.argmax(q_values))

        # Calculate confidence based on Q-value separation
        if q_std > 0:
            z_score = (q_max - q_mean) / q_std
            confidence = min(1.0, z_score / 3.0)  # Normalize z-score to confidence
        else:
            confidence = 0.0

        # Only make decision if confident
        if confidence > self.strategy_thresholds['confidence_threshold']:
            reasoning = f"High confidence in action {q_max_idx} (z-score: {z_score:.2f})"
            return q_max_idx, reasoning, confidence

        return None, f"Low Q-value confidence (std: {q_std:.3f})", confidence

    def _meta_strategy_decision(self, state: np.ndarray, q_values: np.ndarray,
                                skills: Dict[str, Any], patterns: List[Dict[str, Any]],
                                env_analysis: Dict[str, Any]) -> Tuple[Optional[int], str, float]:
        """Make decision using meta-level strategy selection."""
        # Analyze past decision success
        strategy_success = self._analyze_strategy_success()

        if not strategy_success:
            return None, "Insufficient meta-strategy data", 0.0

        # Select best performing strategy
        best_strategy = max(strategy_success, key=strategy_success.get)

        # Apply the best strategy
        if best_strategy in self.strategies and best_strategy != 'meta_strategy':
            strategy_func = self.strategies[best_strategy]
            action, reasoning, confidence = strategy_func(
                state, q_values, skills, patterns, env_analysis
            )

            if action is not None:
                meta_reasoning = f"Meta-selected {best_strategy} (success: {strategy_success[best_strategy]:.2f}) - {reasoning}"
                meta_confidence = confidence * strategy_success[best_strategy]
                return action, meta_reasoning, meta_confidence

        return None, "Meta-strategy selection failed", 0.0

    def _is_skill_applicable(self, skill: Dict[str, Any], state: np.ndarray,
                             patterns: List[Dict[str, Any]]) -> bool:
        """Check if a skill is applicable in current context."""
        conditions = skill.get('conditions', {})

        # Check applicability conditions
        when = conditions.get('applicable_when', '')

        if when == 'similar_state_encountered':
            # Always potentially applicable
            return True
        elif when == 'high_confidence_action_available':
            # Check if we have high confidence
            return len(patterns) > 0
        elif when == 'state_features_correlate_with_actions':
            # Check if we have state variation
            return np.std(state) > 0.1
        elif when == 'sufficient_experience':
            # Check experience level
            return len(patterns) >= 5
        else:
            # Default: assume applicable
            return True

    def _calculate_skill_relevance(self, skill: Dict[str, Any], state: np.ndarray,
                                   patterns: List[Dict[str, Any]]) -> float:
        """Calculate how relevant a skill is to current situation."""
        relevance = 0.5  # Base relevance

        # Adjust based on skill type and current context
        skill_type = skill.get('type', '')

        if skill_type == 'action_optimization':
            # More relevant when exploitation is beneficial
            if patterns and patterns[-1].get('interpretation', {}).get('behavioral_state') == 'stable_policy':
                relevance += 0.3

        elif skill_type == 'state_response':
            # More relevant when state varies
            if np.std(state) > 0.5:
                relevance += 0.2

        elif skill_type == 'exploratory_strategy':
            # More relevant in early learning
            if patterns and patterns[-1].get('interpretation', {}).get('learning_phase') in ['early_learning',
                                                                                             'rapid_learning']:
                relevance += 0.3

        # Boost relevance for higher abstraction levels
        abstraction = skill.get('abstraction_level', 'concrete')
        abstraction_boost = {
            'concrete': 0.0,
            'tactical': 0.1,
            'strategic': 0.2,
            'meta': 0.3
        }
        relevance += abstraction_boost.get(abstraction, 0.0)

        return min(1.0, relevance)

    def _extract_action_from_skill(self, skill: Dict[str, Any], q_values: np.ndarray) -> Optional[int]:
        """Extract concrete action from skill definition."""
        parameters = skill.get('parameters', {})

        # Prioritize target_action
        if 'target_action' in parameters:
            action = parameters['target_action']
            if isinstance(action, int) and 0 <= action < len(q_values):
                return action

        # Fallback to dominant_action
        if 'dominant_action' in parameters:
            action = parameters['dominant_action']
            if isinstance(action, int) and 0 <= action < len(q_values):
                return action

        # Fallback to Q-value-based action for action_optimization skills
        skill_type = skill.get('type', '')
        if skill_type == 'action_optimization' and len(q_values) > 0:
            return int(np.argmax(q_values))

        self.logger.warning(f"Could not extract action from skill: {skill}")
        return None

    def _record_decision(self, strategy: str, action: Optional[int],
                         reasoning: str, confidence: float):
        """Record decision for learning."""
        decision = {
            'strategy': strategy,
            'action': action,
            'reasoning': reasoning,
            'confidence': confidence,
            'timestamp': len(self.decision_history)
        }

        self.decision_history.append(decision)

        # Keep history bounded
        if len(self.decision_history) > self.max_history:
            self.decision_history = self.decision_history[-self.max_history:]

    def _analyze_strategy_success(self) -> Dict[str, float]:
        """Analyze success rate of different strategies."""
        if len(self.decision_history) < 10:
            return {}

        # Group decisions by strategy
        strategy_groups = {}
        for decision in self.decision_history:
            strategy = decision['strategy']
            if strategy not in strategy_groups:
                strategy_groups[strategy] = []
            strategy_groups[strategy].append(decision)

        # Calculate success metric (using confidence as proxy)
        strategy_success = {}
        for strategy, decisions in strategy_groups.items():
            if len(decisions) >= 3:  # Minimum samples
                avg_confidence = np.mean([d['confidence'] for d in decisions])
                # Weight by number of successful decisions (action not None)
                success_rate = sum(1 for d in decisions if d['action'] is not None) / len(decisions)
                strategy_success[strategy] = avg_confidence * success_rate

        return strategy_success

    def update_decision_outcome(self, decision_id: int, reward: float, success: bool):
        """Update decision history with outcome (for future learning)."""
        # This method can be extended to track decision outcomes
        # For now, it's a placeholder for future enhancement
        pass