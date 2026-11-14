# Planet X and SPHEREx | Development and submission

## Start a development shell

```bash
cd /srv/nsac/spherex
source .tooling/activate.sh
```

The workspace has Node 24 LTS, npm, Vite, TypeScript, Python 3.12, FastAPI, Uvicorn, pytest, Astropy, astroquery, PyVO, NumPy, reproject, Pillow, and Matplotlib. The npm lockfile is in `.tooling/js/` and the installed Python versions are in `.tooling/python-lock.txt`. Keep the local installs out of Git. Add the app's own dependency manifests once the team chooses what to build.

The server workspace has a local First Light browser fixture outside this repository's project files. To preview it from there:

```bash
vite test --host 127.0.0.1 --port 5173 --strictPort
```

Start a fresh Codex chat in the existing SSH project at `/srv/nsac` and tell it to work in `/srv/nsac/spherex`. Playwright is registered for the server user. Run `codex mcp list` to see the registration. Ask Codex to visit `http://127.0.0.1:5173/`, interact with the page, and inspect a screenshot. For manual preview from another machine, forward port 5173 over SSH and open the same URL on that machine.

Playwright uses an isolated, headless Chromium instance. Chromium's browser sandbox cannot start on this host, so this setup is for previews of code the team trusts on loopback ports 5173 and 4173.

Git and the GitHub CLI are installed. If you want to use `gh` from the server to create or push a repo, authenticate to your team's GitHub account with `gh auth login --hostname github.com --web`.

## Challenge references

- The [official challenge](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/) calls for a public web tool that takes right ascension and declination and plays SPHEREx observations of that sky region over time. Its named test targets are Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, and R Draconis.
- Use the [IRSA archive guide](https://irsa.ipac.caltech.edu/spherex-archive-documentation/) for current data releases and the [official IRSA tutorials](https://caltech-ipac.github.io/irsa-tutorials/spherex/) for querying observations and fetching FITS cutouts. Record the specific release and its DOI when using its data.
- The [Playwright MCP](https://github.com/microsoft/playwright-mcp) is installed for local visual QA. The official [Playwright CLI and skills](https://github.com/microsoft/playwright-cli) are another option for repeated browser checks from the terminal. The GitHub plugin is installed in the Codex app. The command-line astronomy packages can query IRSA directly.

## Submit on November 14–15, 2026

The organizers say project work starts at the hackathon opening. Submission opens Saturday, November 14 at 09:00 and closes Sunday, November 15 at 23:59 in your Local Event's time zone. For the Universal Event, use the Team Owner's local time. Confirm any separate pitch time with your Local Lead. [Organizer start guidance](https://github.com/nasa/spaceapps/discussions/1858) · [2026 Project Submission Guide](https://www.spaceappschallenge.org/resources/project-submission-guide/)

1. Sign in to Space Apps and open **Profile icon → My Team → Project → Edit**. Confirm all teammates are registered and confirmed for the same event.
2. Fill in the title, summary, detailed description, NASA data, and other references. Use English in the form. Global Award eligibility requires at least one NASA data source or resource. Cite the data, tools, and third-party materials you used and document the relevant licenses. Add an open-source license for your original code. [2026 Participant Terms](https://www.spaceappschallenge.org/legal/)
3. For **Link to Final Project**, use a public GitHub repo or the live web app. For this challenge, make the app usable without a login and include the source link in the description. Add the app URL and instructions to the repo README. [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) can serve a static build. A live Python API needs separate hosting.
4. For **Link to Project Demo**, share a video of at most 30 seconds or a deck of up to seven slides including the title and intro. Slides must be in English. Videos in another language need English subtitles. Test both submission URLs in a signed-out browser.
5. Record how Codex and other AI tools were used in the form's **Use of Super Intelligence** field. The guide allows AI assistance and asks teams to originate their solution ideas. It requires descriptive text and metadata for AI-generated code and data, and visible labels on AI-generated images or videos.
6. Check the terms and originality boxes, click **Submit for Judging**, and verify the confirmation banner. You can edit and resubmit before the cutoff.
