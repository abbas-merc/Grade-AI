/**
 * components/TopicChips.tsx — Topic selector chip row for the paper generator.
 *
 * Behaviour:
 *   - An "All" chip leads the row. It is visually active (filled) exactly when
 *     every topic is selected.
 *   - Tapping "All" selects every topic (or clears the selection if all were
 *     already selected).
 *   - Tapping an individual chip toggles just that topic. So deselecting one
 *     while "All" is active drops "All" but keeps the rest; selecting the last
 *     missing topic re-activates "All" automatically.
 *
 * Selection state is owned by the parent; this component is presentational and
 * reports changes through `onChange`. The parent sends the resolved topic
 * strings to the API (never the word "all").
 */

import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";

import { COLORS, RADIUS, SPACING, FONT, ON } from "../constants/theme";

interface ChipProps {
  label: string;
  active: boolean;
  onPress: () => void;
}

function Chip({ label, active, onPress }: ChipProps) {
  return (
    <TouchableOpacity
      style={[styles.chip, active ? styles.chipActive : styles.chipInactive]}
      onPress={onPress}
      activeOpacity={0.8}
    >
      <Text style={[styles.chipText, active ? styles.chipTextActive : styles.chipTextInactive]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

interface TopicChipsProps {
  topics: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}

/** Title-case a topic key for display, e.g. "algebra" -> "Algebra". */
function labelFor(topic: string): string {
  return topic.length ? topic[0].toUpperCase() + topic.slice(1) : topic;
}

export default function TopicChips({ topics, selected, onChange }: TopicChipsProps) {
  const allSelected = topics.length > 0 && selected.length === topics.length;

  const toggleAll = () => onChange(allSelected ? [] : [...topics]);

  const toggleTopic = (topic: string) =>
    onChange(
      selected.includes(topic)
        ? selected.filter((t) => t !== topic)
        : [...selected, topic]
    );

  return (
    <View style={styles.row}>
      <Chip label="All" active={allSelected} onPress={toggleAll} />
      {topics.map((topic) => (
        <Chip
          key={topic}
          label={labelFor(topic)}
          active={selected.includes(topic)}
          onPress={() => toggleTopic(topic)}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: SPACING.sm,
  },
  chip: {
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.xl,
    borderWidth: 1,
  },
  chipActive: {
    backgroundColor: COLORS.primary,
    borderColor: COLORS.primary,
  },
  chipInactive: {
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
  },
  chipText: {
    fontSize: 14,
    fontWeight: FONT.medium,
  },
  chipTextActive: {
    color: COLORS.card,
  },
  chipTextInactive: {
    color: ON.primaryText,
  },
});
