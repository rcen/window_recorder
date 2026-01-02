Project Spec: Agentic Productivity Dashboard
1. Context & User Profile
User Role: Software Engineer specializing in Computer Vision and Agentic Systems.

Current State: Struggles with the "Second Week Slump," high context-switching costs, and "morning depression".

Data Source: Local activity monitor tracking window titles, categories (learning, coding, wasted, etc.), and durations.

2. Core Metrics & Logic
The Agent should monitor and report on these specific KPIs derived from the logs:

The Waste Ratio: Target < 15%. If "wasted" time (Facebook, shopping) exceeds this, trigger a "Reset" alert.

The 1:5 Vibe-to-Job Ratio: For every 50 minutes in the "Coding/Learning" categories, the user must log 10 minutes in "Job Search" or "Current Job".

Focus Streaks: Monitor the "Longest Streak" (Current record: 52 mins). Notify the user when they are 5 minutes away from breaking their daily record.

The Morning Shield: Monitor activity between 8:00 AM and 11:00 AM. Flag any "Wasted" category entry that occurs before at least 10 minutes of "Coding" or "Docs".

3. Agentic Behavioral Rules (The "Coach" Layer)
The "Timesheet" Guardrail: On Fridays/Saturdays, the Agent must prioritize "Must Done" tasks (Timesheets, Noah's Chinese Homework) before allowing "Gaming" or "Learning" categories.

The Friction Hack: If a "Wasted" spike is detected, the Agent should suggest an "MVD" (Minimum Viable Day) task: 10 pushups or 1 LeetCode problem.

Version Control Check: If "Coding" is active for > 60 mins without a Git commit, remind the user that "documentation generation requires version control".

4. set a separated rules for saturday/sunday and holidays. I think I earn some rest on those days.
   
5. Integration Points for Copilot
Input: Parse the index.html or the underlying log file that generates the "Activity Summary" table.

Output: display the summary in the index.html, so that the current workflow do not need to change much. 

 A terminal-based summary or a simple local JSON API that can be consumed by a tray notification app. 