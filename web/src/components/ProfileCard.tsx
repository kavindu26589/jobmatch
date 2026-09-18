import { useEffect, useState } from "react";
import { replaceOriginal, useCv } from "../cv";
import type { ContactInfo, ResumeProfile } from "../types";
import { toast } from "./Toast";

function esc(value: string): string {
  return value.replace(/[&<>"]/g, (c) => {
    switch (c) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      default:
        return "&quot;";
    }
  });
}

const CONTACT_FIELDS: { key: keyof ContactInfo; label: string; placeholder: string }[] = [
  { key: "name", label: "Name", placeholder: "Full name" },
  { key: "email", label: "Email", placeholder: "you@example.com" },
  { key: "phone", label: "Phone", placeholder: "+1…" },
  { key: "location", label: "Location", placeholder: "City, Country" },
  { key: "linkedin", label: "LinkedIn", placeholder: "linkedin.com/in/…" },
  { key: "github", label: "GitHub", placeholder: "github.com/…" },
  { key: "website", label: "Website", placeholder: "https://…" },
];

function fold(text: string, oldValue: string, newValue: string): string | null {
  if (!oldValue) return null;
  const res = replaceOriginal(text, oldValue, newValue);
  return res.applied !== "none" ? res.next : null;
}

function removeToken(text: string, token: string): string | null {
  if (!token) return null;
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(^|[^A-Za-z0-9])${escaped}(?=[^A-Za-z0-9]|$)`, "i");
  const m = re.exec(text);
  if (!m) return null;
  const start = m.index + m[1].length;
  return text.slice(0, start) + text.slice(start + token.length);
}

export default function ProfileCard({ profile, editable = false }: { profile: ResumeProfile; editable?: boolean }) {
  const cv = useCv();
  const [draft, setDraft] = useState<ContactInfo>({ ...profile.contact });
  const [removed, setRemoved] = useState<Set<string>>(new Set());

  useEffect(() => {
    setDraft({ ...profile.contact });
    setRemoved(new Set());
  }, [profile]);

  const c = profile.contact;
  const skills = [...profile.hard_skills, ...profile.soft_skills.filter((s) => !profile.hard_skills.includes(s))];

  const commitField = (key: keyof ContactInfo, oldValue: string | null | undefined, newValue: string) => {
    if (oldValue === newValue) return;
    const trimmed = newValue.trim();
    const next = fold(cv.text, oldValue ?? "", trimmed);
    if (next === null || next === cv.text) {
      toast(`${key}: not found in CV — edit manually`, "err");
      return;
    }
    cv.setText(next);
    toast(`${key} updated in CV`, "ok");
  };

  const removeSkill = (skill: string) => {
    const next = removeToken(cv.text, skill);
    if (next === null || next === cv.text) {
      toast(`"${skill}" not found in CV — remove manually`, "err");
      return;
    }
    setRemoved((prev) => new Set(prev).add(skill));
    cv.setText(next);
    toast(`Removed "${skill}" from CV`, "ok");
  };

  return (
    <div className="card">
      <div className="profile-head">
        <h3>{c.name || "Candidate"}</h3>
        {profile.target_titles.length > 0 && (
          <span className="caption"> · {profile.target_titles.join(" · ")}</span>
        )}
        {editable && <span className="chip chip-ok">editable</span>}
      </div>

      {editable ? (
        <div className="grid profile-fields">
          {CONTACT_FIELDS.map((f) => (
            <label key={f.key}>
              {f.label}
              <input
                value={draft[f.key] ?? ""}
                placeholder={f.placeholder}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                onBlur={(e) => {
                  const oldValue = c[f.key];
                  const newValue = e.target.value;
                  if (oldValue !== newValue) commitField(f.key, oldValue ?? "", newValue);
                }}
              />
            </label>
          ))}
        </div>
      ) : (
        (c.email || c.location || c.github || c.linkedin) && (
          <p className="caption">{[c.email, c.location, c.github, c.linkedin].filter(Boolean).join(" · ")}</p>
        )
      )}

      {profile.summary && <p>{profile.summary}</p>}

      {skills.length > 0 && (
        <div className="skills">
          {skills
            .filter((s) => !removed.has(s))
            .map((s) => (
              <span key={s} className="chip chip-green">
                {s}
                {editable && (
                  <button
                    type="button"
                    className="chip-x"
                    title={`Remove "${s}" from the CV`}
                    aria-label={`Remove ${s}`}
                    onClick={() => removeSkill(s)}
                  >
                    ✕
                  </button>
                )}
              </span>
            ))}
        </div>
      )}

      {profile.experience.length > 0 && (
        <div className="exp">
          {profile.experience.map((e, i) => (
            <div key={`${e.company}-${i}`} className="exp-item">
              <b>
                {e.title || "—"} @ {e.company || "—"}
              </b>
              {e.start_date || e.end_date ? (
                <span className="caption">
                  {" "}
                  · {e.start_date ?? ""} — {e.end_date ?? "now"}
                </span>
              ) : null}
              {e.bullets.length > 0 && (
                <ul>
                  {e.bullets.map((b, j) => (
                    <li key={j}>{esc(b)}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}