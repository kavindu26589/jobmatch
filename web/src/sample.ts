export const SAMPLE_RESUME = `Jane A. Martinez
jane.martinez@example.com | (555) 014-2233 | New York, NY
linkedin.com/in/janemartinez | github.com/janemartinez

SUMMARY
Product-focused software engineer with 6 years of experience building web
applications end to end, from API design to polished user interfaces.
Accustomed to shipping within small cross-functional teams and passionate
about reliability, accessibility, and measurable outcomes.

SKILLS
TypeScript, React, Node.js, Python, FastAPI, PostgreSQL, Docker, AWS (EC2,
S3), GraphQL, Jest, Playwright, CI/CD, observability with Datadog

EXPERIENCE
Senior Software Engineer - BrightLoop (2021 - Present)
- Led a 3-person team rebuilding the customer dashboard in React,
  cutting load time by 40%.
- Designed and shipped a GraphQL gateway handling 2M requests/day.
- Introduced automated Playwright coverage, reducing regressions by 60%.
Software Engineer - Northwind Labs (2018 - 2021)
- Built REST and background job services in Node.js and Python.
- Migrated core services to Docker and AWS, cutting deploy time in half.
- Contributed to company design system used across seven products.

EDUCATION
B.S. Computer Science - University of Michigan (2014 - 2018)

PROJECTS
resumeforge.dev - AI-assisted resume editor serving 4k weekly users;
TypeScript monorepo with FastAPI scoring backend.`;

export function wordCount(text: string): number {
  return (text.trim().match(/\S+/g) ?? []).length;
}

export function charCount(text: string): number {
  return text.length;
}