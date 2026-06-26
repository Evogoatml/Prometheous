"""
Pattern interpreter for neural-symbolic bridge.

This module interprets patterns from the neural brain and translates them
into symbolic concepts that can be used for reasoning and skill discovery.
"""

import numpy as np
from typing import Dict, Any, List, Optional
import logging


class PatternInterpreter:
    """
    Interprets neural patterns to extract symbolic meaning.

    This is the bridge between neural learning and symbolic reasoning,
    translating activation patterns and learning trajectories into
    abstract concepts.
    """

    def __init__(self):
        """Initialize the pattern interpreter."""
        self.logger = logging.getLogger(self.__class__.__name__)

        # Pattern templates for recognition
        self.pattern_templates = {
            'convergence': self._detect_convergence_pattern,
            'oscillation': self._detect_oscillation_pattern,
            'improvement': self._detect_improvement_pattern,
            'exploration': self._detect_exploration_pattern,
            'exploitation': self._detect_exploitation_pattern,
            'adaptation': self._detect_adaptation_pattern
        }

        # Interpretation history for meta-analysis
        self.interpretation_history = []
        self.max_history = 100

    def interpret(self, neural_insights: Dict[str, Any],
                 cluster_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Interpret neural insights into symbolic concepts.

        Args:
            neural_insights: Insights from neural brain including patterns,
                           trajectories, and performance metrics
            cluster_context: Optional cluster information from skill discovery

        Returns:
            Symbolic interpretation of neural patterns
        """
        interpretation = {
            'detected_patterns': [],
            'behavioral_state': 'unknown',
            'learning_phase': 'unknown',
            'skill_indicators': [],
            'confidence': 0.0,
            'recommendations': [],
            'cluster_context': cluster_context
        }

        # Extract key information
        pattern_summary = neural_insights.get('pattern_summary', {})
        learning_trajectory = neural_insights.get('learning_trajectory', {})
        emerging_patterns = neural_insights.get('emerging_patterns', [])
        performance_metrics = neural_insights.get('performance_metrics', {})

        # Detect patterns
        for pattern_name, detector in self.pattern_templates.items():
            result = detector(neural_insights)
            if result['detected']:
                interpretation['detected_patterns'].append({
                    'name': pattern_name,
                    'confidence': result['confidence'],
                    'details': result.get('details', {})
                })

        # Determine behavioral state
        interpretation['behavioral_state'] = self._determine_behavioral_state(
            pattern_summary, emerging_patterns
        )

        # Determine learning phase
        interpretation['learning_phase'] = self._determine_learning_phase(
            learning_trajectory, performance_metrics
        )

        # Extract skill indicators
        interpretation['skill_indicators'] = self._extract_skill_indicators(
            emerging_patterns, pattern_summary, cluster_context
        )

        # Calculate overall confidence
        if interpretation['detected_patterns']:
            confidences = [p['confidence'] for p in interpretation['detected_patterns']]
            interpretation['confidence'] = np.mean(confidences)

        # Generate recommendations
        interpretation['recommendations'] = self._generate_recommendations(
            interpretation
        )

        # Store in history
        self._update_history(interpretation)

        return interpretation

    def _detect_convergence_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect if learning is converging to stable behavior."""
        trajectory = insights.get('learning_trajectory', {})
        pattern_summary = insights.get('pattern_summary', {})

        result = {'detected': False, 'confidence': 0.0}

        # Check loss trend
        loss_trend = trajectory.get('loss_trend', 0)
        stability = trajectory.get('stability', 0)
        pattern_stability = pattern_summary.get('pattern_stability', 0)

        # More lenient convergence detection
        # Original: loss_trend < -0.001 AND stability > 0.7 AND pattern_stability > 0.6
        # New: Multiple paths to convergence
        convergence_detected = False

        # Path 1: All conditions met (original)
        if loss_trend < -0.001 and stability >= 0.7 and pattern_stability > 0.6:
            convergence_detected = True

        # Path 2: High pattern stability with decent overall stability
        elif stability >= 0.7 and pattern_stability >= 0.8:
            convergence_detected = True

        # Path 3: Strong loss trend with good stability
        elif loss_trend <= -0.01 and stability >= 0.7:
            convergence_detected = True

        if convergence_detected:
            result['detected'] = True
            result['confidence'] = min(1.0, (stability + pattern_stability) / 2)
            result['details'] = {
                'loss_trend': loss_trend,
                'stability': stability,
                'pattern_stability': pattern_stability
            }

        return result

    def _detect_oscillation_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect oscillating behavior patterns."""
        pattern_summary = insights.get('pattern_summary', {})

        result = {'detected': False, 'confidence': 0.0}

        # Check action distribution
        action_dist = pattern_summary.get('action_distribution', {})
        if len(action_dist) >= 2:
            values = list(action_dist.values())
            if len(values) >= 2:
                # Check if actions are alternating
                max_freq = max(values)
                min_freq = min(values)
                total = sum(values)

                if total > 10 and min_freq / total > 0.3 and max_freq / total < 0.7:
                    result['detected'] = True
                    result['confidence'] = 1.0 - abs(0.5 - max_freq / total) * 2
                    result['details'] = {
                        'action_balance': min_freq / max_freq
                    }

        return result

    def _detect_improvement_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect consistent improvement in performance."""
        trajectory = insights.get('learning_trajectory', {})
        performance = insights.get('performance_metrics', {})

        result = {'detected': False, 'confidence': 0.0}

        reward_trend = trajectory.get('reward_trend', 0)
        is_improving = trajectory.get('is_improving', False)

        if is_improving and reward_trend > 0.01:
            result['detected'] = True
            result['confidence'] = min(1.0, reward_trend * 10)
            result['details'] = {
                'reward_trend': reward_trend,
                'average_reward': performance.get('total_reward', 0) / max(1, performance.get('episode_count', 1))
            }

        return result

    def _detect_exploration_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect exploration behavior."""
        pattern_summary = insights.get('pattern_summary', {})

        result = {'detected': False, 'confidence': 0.0}

        # Check action distribution entropy
        action_dist = pattern_summary.get('action_distribution', {})
        if action_dist:
            total = sum(action_dist.values())
            if total > 0:
                # Calculate entropy
                probs = [count / total for count in action_dist.values()]
                entropy = -sum(p * np.log(p + 1e-8) for p in probs)
                max_entropy = np.log(len(action_dist))

                if max_entropy > 0:
                    normalized_entropy = entropy / max_entropy

                    if normalized_entropy > 0.8:
                        result['detected'] = True
                        result['confidence'] = normalized_entropy
                        result['details'] = {
                            'entropy': entropy,
                            'normalized_entropy': normalized_entropy
                        }

        return result

    def _detect_exploitation_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect exploitation behavior."""
        pattern_summary = insights.get('pattern_summary', {})

        result = {'detected': False, 'confidence': 0.0}

        # Check if one action dominates
        action_dist = pattern_summary.get('action_distribution', {})
        if action_dist:
            total = sum(action_dist.values())
            if total > 10:  # Need enough samples
                max_count = max(action_dist.values())
                dominance = max_count / total

                if dominance > 0.7:
                    result['detected'] = True
                    result['confidence'] = dominance
                    result['details'] = {
                        'dominant_action': max(action_dist, key=action_dist.get),
                        'dominance': dominance
                    }

        return result

    def _detect_adaptation_pattern(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Detect adaptation to changing conditions."""
        emerging_patterns = insights.get('emerging_patterns', [])

        result = {'detected': False, 'confidence': 0.0}

        # Look for state-action correlations
        for pattern in emerging_patterns:
            if pattern.get('type') == 'state_action_correlation':
                result['detected'] = True
                result['confidence'] = pattern.get('confidence', 0.5)
                result['details'] = {
                    'correlation_strength': pattern.get('strength', 0)
                }
                break

        return result

    def _determine_behavioral_state(self, pattern_summary: Dict[str, Any],
                                    emerging_patterns: List[Dict[str, Any]]) -> str:
        """Determine the current behavioral state."""
        # Check pattern stability
        stability = pattern_summary.get('pattern_stability', 0)

        # Check for dominant patterns
        action_preferences = [p for p in emerging_patterns
                              if p.get('type') == 'action_preference']

        if stability > 0.8 and action_preferences:
            return 'stable_policy'
        elif stability > 0.5:
            return 'converging'
        elif stability < 0.3:
            return 'exploring'
        else:
            return 'transitioning'

    def _determine_learning_phase(self, trajectory: Dict[str, Any],
                                  performance: Dict[str, Any]) -> str:
        """Determine the current learning phase."""
        if trajectory.get('status') == 'insufficient_data':
            return 'initial'

        is_improving = trajectory.get('is_improving', False)
        stability = trajectory.get('stability', 0)
        episodes = performance.get('episode_count', 0)

        if episodes < 10:
            return 'early_learning'
        elif is_improving and stability < 0.5:
            return 'rapid_learning'
        elif is_improving and stability >= 0.5:
            return 'refinement'
        elif not is_improving and stability > 0.7:
            return 'plateau'
        else:
            return 'unstable'

    def _extract_skill_indicators(self, emerging_patterns: List[Dict[str, Any]],
                              pattern_summary: Dict[str, Any],
                              cluster_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Extract indicators of emerging skills."""
        indicators = []

        # Action preferences as skill indicators
        for pattern in emerging_patterns:
            if pattern.get('type') == 'action_preference':
                if pattern.get('average_reward', 0) > 0:
                    indicators.append({
                        'type': 'successful_action_pattern',
                        'description': f"Action {pattern.get('action')} yields positive rewards",
                        'confidence': pattern.get('confidence', 0),
                        'evidence': {
                            'action': pattern.get('action'),
                            'frequency': pattern.get('frequency', 0),
                            'average_reward': pattern.get('average_reward', 0)
                        }
                    })

        # Pattern stability as skill indicator
        stability = pattern_summary.get('pattern_stability', 0)
        if stability > 0.7:
            indicators.append({
                'type': 'stable_behavior',
                'description': 'Consistent behavioral patterns emerging',
                'confidence': stability,
                'evidence': {
                    'pattern_count': pattern_summary.get('pattern_count', 0),
                    'decision_count': pattern_summary.get('decision_count', 0)
                }
            })

        # Reward correlation as skill indicator
        avg_rewards = pattern_summary.get('avg_reward_by_action', {})
        for action, avg_reward in avg_rewards.items():
            if avg_reward > 1.0:  # Threshold for "good" reward
                indicators.append({
                    'type': 'reward_maximization',
                    'description': f'Learned to maximize reward with action {action}',
                    'confidence': min(1.0, avg_reward / 5.0),  # Scale confidence
                    'evidence': {
                        'action': action,
                        'average_reward': avg_reward
                    }
                })

        # Add cluster-based skill indicators when cluster_context is provided
        if cluster_context:
            indicators.append({
                'type': 'cluster_membership',
                'description': f'Belongs to cluster {cluster_context["cluster_id"]} with high confidence',
                'confidence': cluster_context.get('confidence', 0),
                'evidence': {
                    'cluster_id': cluster_context['cluster_id'],
                    'cluster_confidence': cluster_context.get('confidence', 0)
                }
            })

            if 'recommended_action' in cluster_context:
                indicators.append({
                    'type': 'cluster_action_preference',
                    'description': f'Cluster recommends action {cluster_context["recommended_action"]}',
                    'confidence': cluster_context.get('action_confidence', 0),
                    'evidence': {
                        'recommended_action': cluster_context['recommended_action'],
                        'expected_reward': cluster_context.get('expected_reward', 0)
                    }
                })

        return indicators

    def _generate_recommendations(self, interpretation: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on interpretation."""
        recommendations = []

        # Based on learning phase
        phase = interpretation['learning_phase']
        if phase == 'early_learning':
            recommendations.append('Continue exploration to discover environment dynamics')
        elif phase == 'plateau':
            recommendations.append('Consider increasing exploration or transferring knowledge')
        elif phase == 'unstable':
            recommendations.append('Focus on stabilizing learning with consistent strategies')

        # Based on behavioral state
        state = interpretation['behavioral_state']
        if state == 'exploring':
            recommendations.append('Good exploration coverage - patterns may emerge soon')
        elif state == 'stable_policy':
            recommendations.append('Policy stabilized - consider extracting transferable skills')

        # Based on detected patterns
        for pattern in interpretation['detected_patterns']:
            if pattern['name'] == 'oscillation':
                recommendations.append('Oscillating behavior detected - may indicate competing strategies')
            elif pattern['name'] == 'convergence':
                recommendations.append('Learning converging - prepare for skill extraction')

        return recommendations

    def _update_history(self, interpretation: Dict[str, Any]):
        """Update interpretation history for meta-analysis."""
        self.interpretation_history.append({
            'timestamp': interpretation.get('timestamp', 0),
            'behavioral_state': interpretation['behavioral_state'],
            'learning_phase': interpretation['learning_phase'],
            'pattern_count': len(interpretation['detected_patterns']),
            'confidence': interpretation['confidence']
        })

        # Keep history bounded
        if len(self.interpretation_history) > self.max_history:
            self.interpretation_history = self.interpretation_history[-self.max_history:]

    def get_meta_insights(self) -> Dict[str, Any]:
        """Get meta-level insights from interpretation history."""
        if not self.interpretation_history:
            return {'status': 'no_history'}

        # Analyze state transitions
        states = [h['behavioral_state'] for h in self.interpretation_history]
        state_transitions = {}
        for i in range(1, len(states)):
            transition = f"{states[i - 1]} -> {states[i]}"
            state_transitions[transition] = state_transitions.get(transition, 0) + 1

        # Analyze phase progression
        phases = [h['learning_phase'] for h in self.interpretation_history]
        phase_progression = []
        current_phase = phases[0]
        for phase in phases[1:]:
            if phase != current_phase:
                phase_progression.append(f"{current_phase} -> {phase}")
                current_phase = phase

        return {
            'total_interpretations': len(self.interpretation_history),
            'state_transitions': state_transitions,
            'phase_progression': phase_progression,
            'average_confidence': np.mean([h['confidence'] for h in self.interpretation_history]),
            'stability_trend': self._calculate_stability_trend()
        }

    def _calculate_stability_trend(self) -> str:
        """Calculate trend in behavioral stability."""
        if len(self.interpretation_history) < 10:
            return 'insufficient_data'

        recent = self.interpretation_history[-10:]
        stable_states = ['stable_policy', 'converging']

        stable_count = sum(1 for h in recent if h['behavioral_state'] in stable_states)

        if stable_count >= 8:
            return 'highly_stable'
        elif stable_count >= 5:
            return 'stabilizing'
        elif stable_count >= 2:
            return 'variable'
        else:
            return 'unstable'