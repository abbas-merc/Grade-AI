/**
 * app/generate-paper.tsx — Custom Paper Generator: the request form.
 *
 * The teacher picks a paper type (Paper 2 / Paper 4 / Both), a total mark target
 * (preset chips or a custom value), a difficulty, and topics, then taps
 * Generate. A reactive "Available: X marks" line shows the pool ceiling for the
 * current selection BEFORE generating, so they never aim above what exists.
 *
 * On success we navigate to /generated-paper with the API response serialised.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  StyleSheet,
} from "react-native";
import { useRouter } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";

import TopicChips from "../components/TopicChips";
import { getQuestionPool, generatePaper } from "../services/api";
import type {
  GeneratorDifficulty,
  GeneratorPool,
  PaperType,
} from "../types/paperGenerator";
import { COLORS, RADIUS, SPACING, FONT } from "../constants/theme";

const SUBJECT = "math";
const DIFFICULTIES: GeneratorDifficulty[] = ["mixed", "easy", "medium", "hard"];
const MARK_PRESETS = [40, 60, 80, 100];
const MIN_MARKS = 20;
const MAX_MARKS = 200;

// Mirrors the backend selector bounds (_MIN_QUESTIONS / _MAX_QUESTIONS) so the
// "closest achievable totals" hint matches what Generate can actually build.
const MIN_Q = 3;
const MAX_Q = 12;

// AsyncStorage key: the last School Name the teacher used, pre-filled next time
// so they don't retype it for every paper.
const SCHOOL_NAME_KEY = "@gradeai_school_name";

const PAPER_TYPES: { value: PaperType; label: string; desc: string }[] = [
  { value: "P2", label: "Paper 2", desc: "Non-calculator, structured questions" },
  { value: "P4", label: "Paper 4", desc: "Calculator allowed, longer structured questions" },
  { value: "both", label: "Both", desc: "Mix from both paper types" },
];

// The pool is static per subject, so cache it at module scope and reuse across
// every mount instead of re-fetching. Cleared only when the app process restarts.
let poolCache: GeneratorPool | null = null;

function paperTypeLabel(pt: PaperType): string {
  return pt === "both" ? "Paper 2 + 4" : pt === "P2" ? "Paper 2" : "Paper 4";
}

export default function GeneratePaperScreen() {
  const router = useRouter();

  const [pool, setPool] = useState<GeneratorPool | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [paperType, setPaperType] = useState<PaperType>("both");
  // Total marks is either an active preset chip OR a custom typed value — the
  // two are mutually exclusive so the custom field is always obviously usable.
  const [preset, setPreset] = useState<number | null>(60);
  const [custom, setCustom] = useState("");
  const [difficulty, setDifficulty] = useState<GeneratorDifficulty>("mixed");
  // Optional school name printed in the generated paper's header. Persisted to
  // AsyncStorage so it's remembered between papers (Part 6).
  const [schoolName, setSchoolName] = useState("");

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadPool = async (force = false) => {
    if (!force && poolCache) {
      setPool(poolCache);
      setTopics(poolCache.topics);
      setSelectedTopics(poolCache.topics);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const fetched = await getQuestionPool(SUBJECT);
      poolCache = fetched;
      setPool(fetched);
      setTopics(fetched.topics);
      setSelectedTopics(fetched.topics); // default: All selected
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load questions");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPool();
  }, []);

  // Pre-fill the School Name with the last value the teacher used.
  useEffect(() => {
    AsyncStorage.getItem(SCHOOL_NAME_KEY)
      .then((v) => {
        if (v) setSchoolName(v);
      })
      .catch(() => {
        /* non-fatal: just start with an empty field */
      });
  }, []);

  const onSchoolNameChange = (t: string) => {
    setSchoolName(t);
    // Remember it for next time (fire-and-forget).
    AsyncStorage.setItem(SCHOOL_NAME_KEY, t).catch(() => {});
  };

  // Effective requested marks: the active preset, else the parsed custom value.
  const marks = preset != null ? preset : parseInt(custom, 10);
  const marksValid = Number.isFinite(marks) && marks >= MIN_MARKS && marks <= MAX_MARKS;

  // Reactive pool ceiling for the current paperType + difficulty + topics.
  const available = useMemo(() => {
    if (!pool) return { count: 0, marks: 0 };
    const topicSet = new Set(selectedTopics);
    let count = 0;
    let total = 0;
    for (const q of pool.questions) {
      if (paperType !== "both" && q.paperType !== paperType) continue;
      if (difficulty !== "mixed" && q.difficulty !== difficulty) continue;
      if (topicSet.size > 0 && !topicSet.has(q.topic)) continue;
      count += 1;
      total += q.marks;
    }
    return { count, marks: total };
  }, [pool, paperType, difficulty, selectedTopics]);

  // The marks of every question matching the current filters (same predicate as
  // `available`), used for the subset-sum reachability below.
  const filteredMarks = useMemo(() => {
    if (!pool) return [] as number[];
    const topicSet = new Set(selectedTopics);
    const out: number[] = [];
    for (const q of pool.questions) {
      if (paperType !== "both" && q.paperType !== paperType) continue;
      if (difficulty !== "mixed" && q.difficulty !== difficulty) continue;
      if (topicSet.size > 0 && !topicSet.has(q.topic)) continue;
      if (q.marks > 0) out.push(q.marks);
    }
    return out;
  }, [pool, paperType, difficulty, selectedTopics]);

  // Every exam total reachable by picking between MIN_Q and MAX_Q questions from
  // the filtered pool. This mirrors the backend subset-sum selector (which caps
  // at 12 questions), so the "closest achievable" hint below always matches what
  // Generate can actually produce. Bounded 0/1 knapsack over (count, sum).
  const reachableTotals = useMemo(() => {
    const n = filteredMarks.length;
    const maxK = Math.min(MAX_Q, n);
    const reach: Set<number>[] = Array.from(
      { length: maxK + 1 },
      () => new Set<number>()
    );
    reach[0].add(0);
    for (const m of filteredMarks) {
      // Walk k high→low so each question is used at most once per subset.
      for (let k = maxK; k >= 1; k--) {
        for (const s of reach[k - 1]) reach[k].add(s + m);
      }
    }
    // Require ≥ MIN_Q questions where the pool allows it (else as many as exist).
    const minK = Math.max(1, Math.min(MIN_Q, maxK));
    const totals = new Set<number>();
    for (let k = minK; k <= maxK; k++) {
      for (const s of reach[k]) if (s > 0) totals.add(s);
    }
    return totals;
  }, [filteredMarks]);

  // When the exact requested total can't be hit, the nearest totals that CAN be.
  const closestTotals = useMemo(() => {
    if (!marksValid || reachableTotals.has(marks)) return null;
    let below = -Infinity;
    let above = Infinity;
    for (const t of reachableTotals) {
      if (t < marks && t > below) below = t;
      if (t > marks && t < above) above = t;
    }
    const options: number[] = [];
    if (Number.isFinite(below)) options.push(below);
    if (Number.isFinite(above)) options.push(above);
    return options.length ? options : null;
  }, [reachableTotals, marks, marksValid]);

  const difficultyLabel = difficulty === "mixed" ? "all-difficulty" : difficulty;
  const exceedsPool = marksValid && marks > available.marks;

  const canGenerate =
    !generating && !loading && marksValid && selectedTopics.length > 0 && available.count > 0;

  const selectPreset = (p: number) => {
    setPreset(p);
    setCustom(""); // tapping a preset clears any custom value
  };

  const onCustomChange = (t: string) => {
    setCustom(t.replace(/[^0-9]/g, ""));
    setPreset(null); // typing a custom value deselects all presets
  };

  const onGenerate = async () => {
    setFormError(null);
    if (!marksValid) {
      setFormError(`Enter a total between ${MIN_MARKS} and ${MAX_MARKS} marks.`);
      return;
    }
    if (selectedTopics.length === 0) {
      setFormError("Select at least one topic.");
      return;
    }

    setGenerating(true);
    try {
      const paper = await generatePaper({
        subject: SUBJECT,
        paperType,
        topics: selectedTopics, // resolved topic strings, never "all"
        totalMarks: marks,
        difficulty,
        schoolName: schoolName.trim(),
      });
      if (paper.questions.length === 0) {
        setFormError(
          "No questions match these settings. Try a different paper type, more topics, another difficulty, or a higher mark total."
        );
        return;
      }
      // Limited pool: the selector never exceeds the target but may fall short.
      if (paper.totalMarks < marks) {
        Alert.alert(
          "Fewer marks available",
          `We could only fit ${paper.totalMarks} marks from the questions matching these settings (you asked for ${marks}). Continue with this paper, or go back and widen the filters.`,
          [
            { text: "Back", style: "cancel" },
            {
              text: "Continue",
              onPress: () =>
                router.push({
                  pathname: "/generated-paper",
                  params: { paper: JSON.stringify(paper) },
                }),
            },
          ]
        );
        return;
      }
      router.push({
        pathname: "/generated-paper",
        params: { paper: JSON.stringify(paper) },
      });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to generate paper.");
    } finally {
      setGenerating(false);
    }
  };

  const activePaperDesc = PAPER_TYPES.find((p) => p.value === paperType)?.desc ?? "";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.label}>Subject</Text>
      <View style={styles.subjectBox}>
        <Text style={styles.subjectText}>Mathematics (0580)</Text>
      </View>

      {/* School name (optional) — printed in the generated paper header and
          remembered for next time. */}
      <Text style={styles.label}>School Name</Text>
      <Text style={styles.subLabel}>Optional — shown on the paper header</Text>
      <TextInput
        style={styles.schoolInput}
        value={schoolName}
        onChangeText={onSchoolNameChange}
        placeholder="e.g. Springfield High School"
        placeholderTextColor={COLORS.textTertiary}
        maxLength={80}
        returnKeyType="done"
      />

      {/* Paper type */}
      <Text style={styles.label}>Paper Type</Text>
      <View style={styles.segmentRow}>
        {PAPER_TYPES.map((p) => {
          const active = paperType === p.value;
          return (
            <TouchableOpacity
              key={p.value}
              style={[styles.segment, active ? styles.segmentActive : styles.segmentInactive]}
              onPress={() => setPaperType(p.value)}
              activeOpacity={0.8}
            >
              <Text style={[styles.segmentText, active ? styles.segmentTextActive : styles.segmentTextInactive]}>
                {p.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <Text style={styles.helperText}>{activePaperDesc}</Text>

      {/* Total marks */}
      <Text style={styles.label}>Total Marks</Text>
      <Text style={styles.subLabel}>Select or enter a custom value</Text>
      <View style={styles.presetRow}>
        {MARK_PRESETS.map((p) => {
          const active = preset === p;
          return (
            <TouchableOpacity
              key={p}
              style={[styles.preset, active ? styles.presetActive : styles.presetInactive]}
              onPress={() => selectPreset(p)}
              activeOpacity={0.8}
            >
              <Text style={[styles.presetText, active ? styles.presetTextActive : styles.presetTextInactive]}>
                {p}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <View style={styles.customRow}>
        <Text style={styles.customLabel}>Or enter custom:</Text>
        <TextInput
          style={[styles.customInput, preset == null && custom !== "" && styles.customInputActive]}
          value={custom}
          onChangeText={onCustomChange}
          keyboardType="number-pad"
          placeholder="e.g. 75"
          placeholderTextColor={COLORS.textTertiary}
          maxLength={3}
        />
      </View>

      {/* Difficulty */}
      <Text style={styles.label}>Difficulty</Text>
      <View style={styles.segmentRow}>
        {DIFFICULTIES.map((d) => {
          const active = difficulty === d;
          return (
            <TouchableOpacity
              key={d}
              style={[styles.segment, active ? styles.segmentActive : styles.segmentInactive]}
              onPress={() => setDifficulty(d)}
              activeOpacity={0.8}
            >
              <Text style={[styles.segmentText, active ? styles.segmentTextActive : styles.segmentTextInactive]}>
                {d[0].toUpperCase() + d.slice(1)}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {/* Topics */}
      <Text style={styles.label}>Topics</Text>
      {loading ? (
        <ActivityIndicator color={COLORS.primary} style={styles.topicsLoading} />
      ) : loadError ? (
        <View>
          <Text style={styles.errorText}>{loadError}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={() => loadPool(true)} activeOpacity={0.8}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <TopicChips topics={topics} selected={selectedTopics} onChange={setSelectedTopics} />
      )}

      {formError ? <Text style={styles.errorText}>{formError}</Text> : null}

      <TouchableOpacity
        style={[styles.generateButton, !canGenerate && styles.buttonDisabled]}
        onPress={onGenerate}
        disabled={!canGenerate}
        activeOpacity={0.8}
      >
        {generating ? (
          <ActivityIndicator color={COLORS.card} />
        ) : (
          <Text style={styles.generateButtonText}>Generate Paper</Text>
        )}
      </TouchableOpacity>

      {/* Reactive pool ceiling — always visible so the teacher knows the limit
          before tapping Generate. */}
      {!loading && !loadError ? (
        <Text style={[styles.availabilityText, exceedsPool && styles.availabilityWarn]}>
          {available.count === 0
            ? `No ${difficultyLabel} questions in ${paperTypeLabel(paperType)} for the selected topics.`
            : `Available: ${available.marks} marks across ${available.count} ${difficultyLabel} ${paperTypeLabel(paperType)} question${available.count === 1 ? "" : "s"}.` +
              (exceedsPool ? ` You asked for ${marks} — the paper will be capped at what fits.` : "")}
        </Text>
      ) : null}

      {/* Closest achievable totals — when the exact requested mark total can't be
          hit with the current filters, tell the teacher which nearby totals CAN,
          so they can adjust rather than just being told it fell short (Part 4). */}
      {!loading && !loadError && available.count > 0 && closestTotals ? (
        <Text style={styles.closestText}>
          {`${marks} marks isn't achievable with these filters — closest options: ${closestTotals
            .map((t) => `${t}`)
            .join(" or ")} marks.`}
        </Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  content: {
    padding: SPACING.lg,
    paddingBottom: SPACING.xxl,
  },
  label: {
    fontSize: 14,
    fontWeight: FONT.medium,
    color: COLORS.textSecondary,
    marginTop: SPACING.lg,
    marginBottom: SPACING.sm,
  },
  subLabel: {
    fontSize: 12,
    color: COLORS.textTertiary,
    marginTop: -SPACING.xs,
    marginBottom: SPACING.sm,
  },
  helperText: {
    fontSize: 13,
    color: COLORS.textTertiary,
    marginTop: SPACING.xs,
  },
  subjectBox: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    padding: SPACING.md,
  },
  subjectText: {
    fontSize: 16,
    color: COLORS.textPrimary,
    fontWeight: FONT.medium,
  },
  schoolInput: {
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
    fontSize: 16,
    color: COLORS.textPrimary,
  },
  // Total marks
  presetRow: {
    flexDirection: "row",
    gap: SPACING.sm,
  },
  preset: {
    flex: 1,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    alignItems: "center",
  },
  presetActive: {
    backgroundColor: COLORS.primary,
    borderColor: COLORS.primary,
  },
  presetInactive: {
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
  },
  presetText: {
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  presetTextActive: {
    color: COLORS.card,
  },
  presetTextInactive: {
    color: COLORS.textSecondary,
  },
  customRow: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: SPACING.md,
    gap: SPACING.md,
  },
  customLabel: {
    fontSize: 14,
    color: COLORS.textSecondary,
  },
  customInput: {
    flex: 1,
    backgroundColor: COLORS.card,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    paddingVertical: SPACING.md,
    paddingHorizontal: SPACING.md,
    fontSize: 16,
    color: COLORS.textPrimary,
  },
  customInputActive: {
    borderColor: COLORS.primary,
    borderWidth: 1.5,
  },
  // Segmented rows (paper type, difficulty)
  segmentRow: {
    flexDirection: "row",
    gap: SPACING.sm,
  },
  segment: {
    flex: 1,
    paddingVertical: SPACING.md,
    borderRadius: RADIUS.lg,
    borderWidth: 1,
    alignItems: "center",
  },
  segmentActive: {
    backgroundColor: COLORS.primary,
    borderColor: COLORS.primary,
  },
  segmentInactive: {
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
  },
  segmentText: {
    fontSize: 13,
    fontWeight: FONT.medium,
  },
  segmentTextActive: {
    color: COLORS.card,
  },
  segmentTextInactive: {
    color: COLORS.textSecondary,
  },
  topicsLoading: {
    alignSelf: "flex-start",
  },
  generateButton: {
    backgroundColor: COLORS.primary,
    borderRadius: RADIUS.lg,
    paddingVertical: SPACING.lg,
    alignItems: "center",
    marginTop: SPACING.xl,
  },
  generateButtonText: {
    color: COLORS.card,
    fontSize: 16,
    fontWeight: FONT.medium,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  availabilityText: {
    fontSize: 13,
    color: COLORS.textSecondary,
    textAlign: "center",
    marginTop: SPACING.md,
    lineHeight: 19,
  },
  availabilityWarn: {
    color: COLORS.warning,
  },
  closestText: {
    fontSize: 13,
    color: COLORS.primary,
    textAlign: "center",
    marginTop: SPACING.sm,
    lineHeight: 19,
  },
  errorText: {
    color: COLORS.fail,
    fontSize: 14,
    marginTop: SPACING.md,
  },
  retryButton: {
    alignSelf: "flex-start",
    marginTop: SPACING.sm,
    paddingHorizontal: SPACING.md,
    paddingVertical: SPACING.sm,
    borderRadius: RADIUS.md,
    backgroundColor: COLORS.primaryLight,
  },
  retryText: {
    color: COLORS.primary,
    fontWeight: FONT.medium,
  },
});
