"""The text of the Help tab.

Rule: <b>bold</b> is used only for names of things you can see and click in the app (buttons, tick boxes, tabs, menu items).
tests/help_test.py checks that every bold name really exists, so this text cannot drift away from the app.
"""
from app import __version__

STYLE = """
<style>
  body { font-size: 10.5pt; }
  h2 { margin-bottom: 4px; }
  h3 { margin-bottom: 2px; }
  code { background: #ececec; padding: 0 3px; }
  table { border-collapse: collapse; }
  td, th { padding: 3px 12px 3px 0; text-align: left; vertical-align: top; }
  .note { color: #666666; }
</style>
"""


def topics(db_path="", backup_folder="", staging_folder=""):
    """[(title, html)] in the order shown. The three folder arguments fill in the 'where is my data' page."""
    db_path, backup_folder, staging_folder = str(db_path), str(backup_folder), str(staging_folder)
    return [
        ("Quick start", STYLE + """
<h2>Quick start</h2>
<ol>
  <li>Open the <b>Builder</b> tab and press <b>Wildcard</b>. A complete prompt appears on the right, in seven paragraphs:
      Subject, Clothing, Action, Environment, Camera, Lighting and Style Details.</li>
  <li>Not happy with one part? Press <b>Reroll</b> on that row for a new pick, or <b>Choose...</b> to pick by hand.</li>
  <li>Happy with a part? Tick <b>Lock</b> on that row, then press <b>Wildcard</b> again. Everything not locked changes,
      and the locked rows stay exactly as they are.</li>
  <li>Press <b>Copy prompt</b> and paste it into ComfyUI. Press <b>Save prompt...</b> to keep it.</li>
</ol>
<p>No AI model is involved. Prompts are put together from your preset library with fixed sentence patterns, so it is
instant, works offline and gives the same wording for the same picks.</p>
"""),
        ("The Builder", STYLE + """
<h2>The Builder</h2>
<p>The left side has one row for each part of the prompt. The <i>Subject</i> box holds the details of the woman: age, skin
tone, hair colour, hair style, eye colour, body, bust size, bust shape, expression, makeup, skin detail, tattoos and piercings.
Below it are single rows for Clothing, Action / Pose, Environment, Camera, Lighting and Style.</p>
<h3>The four buttons on every row</h3>
<table>
  <tr><td><b>Lock</b></td><td>Keeps this pick when you press <b>Wildcard</b> or <b>Clear all</b>.</td></tr>
  <tr><td><b>Choose...</b></td><td>Opens a list of everything that fits this row. Pick a list (or all lists), narrow it with
      the search box, and press <b>Use this</b>. Double-clicking an entry does the same.</td></tr>
  <tr><td><b>Reroll</b></td><td>A new random pick for this row only. It still matches the rest: a new Environment fits your
      pose, and new Clothing fits your pose and setting.</td></tr>
  <tr><td><b>Clear</b></td><td>Empties the row. A row with nothing in it leaves its paragraph out of the prompt.</td></tr>
</table>
<p><b>Reroll filled details</b> (top of the Subject box) gives every unlocked subject detail that already has a pick a new
one. <b>Unlock all</b> removes every lock, and <b>Clear all</b> empties every row that is not locked.</p>
<p>Some entries describe more than one part of the picture at once (a pose that also names the room, for example). Those
show a small grey note under the row, such as <i>Also describes: Environment</i>.</p>
<p>The prompt on the right updates as you change anything. The word count is shown under it.</p>
"""),
        ("The Wildcard button", STYLE + """
<h2>The Wildcard button</h2>
<p><b>Wildcard</b> fills every row that is not locked. It chooses in a sensible order so the parts fit together:</p>
<ol>
  <li>The <i>pose</i> first.</li>
  <li>An <i>environment</i> that suits the pose. Bed poses get bedrooms and hotel rooms, pool poses get pools, yoga gets
      studios and gyms, and so on.</li>
  <li><i>Clothing</i> that suits both. Swimwear by the pool, robes and lingerie in bedrooms and bathrooms, gym wear at the
      gym. Lingerie, robes, swimwear, gym wear, school uniforms and gamer looks are only used in a matching setting.
      A pose that describes its own clothing (about 1 pose in 30) is never used next to a Clothing pick, so a pose and an
      outfit cannot clash. If you lock such a pose, the Wildcard leaves the Clothing row empty; if you put the two together
      by hand, the pose's row shows a warning.</li>
  <li>Camera, lighting and style, then the details of the woman.</li>
</ol>
<p>The wildcard first picks a <i>list</i> and then an entry inside it, so a very long list cannot crowd out a short one.</p>
<h3>The options next to the button</h3>
<table>
  <tr><td><b>Detail</b></td><td><b>Minimal</b>, <b>Normal</b> or <b>Rich</b>: how many of the optional subject details (hair
      style, makeup, tattoos and so on) get added. Age is always included.</td></tr>
  <tr><td><b>Basic</b> and <b>Detailed</b></td><td>Which levels of list the wildcard may use. Basic lists hold short, everyday
      phrases; Detailed lists hold richer descriptions. If you untick both, both are used. If a part has no list at the level
      you chose (age, eye colour, body and bust only have Basic lists; hair style and skin detail only Detailed ones), the other
      level is used for that part, so ticking one level never makes a row go missing.</td></tr>
  <tr><td><b>Whole-scene presets</b></td><td>Off (the default): every prompt has the same seven paragraphs, made only from lists
      that describe one thing. On: the wildcard may also use presets that describe several parts at once, such as movie
      posters, artistic shots and themed scenes. The parts they cover are left out, so the structure varies.</td></tr>
  <tr><td><b>Adult content</b></td><td>Off by default. When ticked, a box appears where you set how often the pose is taken
      from the adult scenes list. An adult scene describes the whole picture, so the wildcard adds no Clothing paragraph and
      skips any other part the scene already mentions.</td></tr>
</table>
"""),
        ("Character LoRAs and eye colour", STYLE + """
<h2>Character LoRAs and eye colour</h2>
<p>A character LoRA usually has the eye colour trained in, so a different colour in the prompt only fights it.</p>
<p>On the <i>Eye colour</i> row press <b>Choose...</b>. The first item in the list is
<b>None &mdash; leave eye colour out of the prompt</b>. Once you pick it:</p>
<ul>
  <li>the row reads <i>None &mdash; left out of the prompt</i> and no eye colour appears in the prompt;</li>
  <li>the wildcard never draws an eye colour, and never draws any entry (from any section) that names one;</li>
  <li>an entry you pick by hand that names an eye colour gets a small warning under its row;</li>
  <li>your choice is remembered next time.</li>
</ul>
<p>To switch it off, choose a real eye colour from the list or press <b>Clear</b> on that row.</p>
"""),
        ("Saved prompts", STYLE + """
<h2>Saved prompts</h2>
<p>Press <b>Save prompt...</b> under the prompt to keep it. You give it a name; the prompt, every pick, your locks and the
eye colour <i>None</i> setting are stored with it.</p>
<p>After you save (or load) a prompt, an <b>Update saved</b> button appears. It replaces the saved version with what you
have now. <b>Save prompt...</b> on a loaded prompt saves a new copy instead.</p>
<h3>The Saved tab</h3>
<ul>
  <li>The search box looks through names, prompts and notes.</li>
  <li>The <i>Notes</i> box saves as you type. Use it for the model, LoRA, seed, or what you liked.</li>
  <li><b>Load into Builder</b> puts all the picks back so you can carry on editing. Double-clicking a prompt does the same.</li>
  <li><b>Copy prompt</b>, <b>Rename...</b> and <b>Delete</b> do what they say.</li>
  <li><b>Export all...</b> writes the prompts shown to a text file.</li>
</ul>
<p>Saved prompts keep working even if you later delete a list, change your presets or reset the library. They are also
kept when you use <b>Reset library...</b>. Prompts that contain an adult scene are hidden in the Saved tab unless
<b>Adult content</b> is ticked in the Builder.</p>
"""),
        ("The Library", STYLE + """
<h2>The Library</h2>
<p>The <b>Library</b> tab shows every preset, organised as Section, then Group, then List. Click a section or group for an
overview, or a list to browse its entries.</p>
<ul>
  <li><b>Basic</b>, <b>Detailed</b> and <b>Scene</b> show or hide lists by level. Scene lists are the ones that describe several
      parts of the picture at once.</li>
  <li><b>Adult content</b> shows the adult lists (hidden by default).</li>
  <li><b>Disabled lists and entries</b> also shows what you have switched off, so you can switch it back on.</li>
  <li>The search box searches inside whatever is selected. The dropdowns above the entries (colour, venue, and so on)
      narrow a long list, and show how many entries each choice leaves.</li>
  <li>The <b>Enabled (used by the builder and wildcard)</b> box switches a single entry off without deleting it.</li>
  <li><b>Copy text</b> copies an entry.</li>
</ul>
<p>The built-in presets can be switched on and off but not edited. That keeps the original library safe.</p>
"""),
        ("Image Analyser", STYLE + """
<h2>Image Analyser</h2>
<p>The <b>Image Analyser</b> tab shows what was used to make an image. Everything is read from the image file on your
computer; nothing is sent anywhere.</p>
<ol>
  <li>Press <b>Browse...</b> and choose the folder where your images are saved (for example ComfyUI's output folder). You can
      also type or paste a folder and press Enter.</li>
  <li>The folders appear on the left. Click one to see its images as thumbnails in the middle, newest first.
      <b>Refresh</b> scans the selected folder again.</li>
  <li>Click an image. It appears larger on the right, and the <b>Metadata</b> tab lists what could be found: prompt, negative
      prompt, model, LoRAs, seed, steps, CFG, sampler, scheduler and denoise. The <b>Raw</b> tab shows the complete stored text.</li>
  <li>Press <b>Copy prompt</b> to copy the prompt.</li>
</ol>
<p>It understands images made by ComfyUI and by Automatic1111-style programs. ComfyUI workflows differ a lot, so some details
can be missing; the Raw tab always has everything that is stored. Only PNG files are listed. An image that has no stored
generation data (for example one that another program re-saved) says so.</p>
"""),
        ("Adding your own presets", STYLE + """
<h2>Adding your own presets</h2>
<h3>A new list</h3>
<p>Press <b>New list...</b>. Give it a name, choose the section and what it is used for (for example Hair colour, Outfit or
Camera angle), and the level. Type or paste one entry per line, or use <b>Load from file...</b> to read a text file.
Bullets and numbering are removed and repeated lines are skipped. Press <b>Create list</b>. The list appears under a group
called <i>My presets</i>.</p>
<p>Scene lists ask which other parts of the picture they also describe. Only Action lists can be marked adult.</p>
<h3>More entries in an existing list</h3>
<p>Select the list and press <b>Add entries...</b>. This works on the built-in lists too; your entries are added after the
built-in ones and marked <i>Added by you</i>.</p>
<h3>Changing what you added</h3>
<ul>
  <li><b>Edit...</b> and <b>Delete</b> (under the entry list) work on entries you added. Built-in entries can only be switched
      off.</li>
  <li>The <b>This list</b> menu has <b>Turn this list off</b> / <b>Turn this list on</b> for any list, and
      <b>Delete this list...</b> for lists you created.</li>
</ul>
<h3>How to word an entry</h3>
<p>Write a short phrase that carries on the sentence the app builds. The app spots the wording and adjusts:</p>
<table>
  <tr><th>Row</th><th>You write</th><th>The prompt says</th></tr>
  <tr><td>Hair colour (with an age)</td><td><code>neon lime hair</code></td><td>A woman in her twenties with neon lime hair.</td></tr>
  <tr><td>Hair style</td><td><code>a sleek high ponytail</code></td><td>She has a sleek high ponytail.</td></tr>
  <tr><td>Clothing</td><td><code>a mustard trench coat over a black bodysuit</code></td><td>She wears a mustard trench coat over a black bodysuit.</td></tr>
  <tr><td>Action / Pose</td><td><code>sitting cross-legged on the floor</code></td><td>She is sitting cross-legged on the floor.</td></tr>
  <tr><td>Environment</td><td><code>a rooftop garden at dusk</code></td><td>The setting is a rooftop garden at dusk.</td></tr>
  <tr><td>Lighting</td><td><code>soft golden hour light</code></td><td>The scene is lit by soft golden hour light.</td></tr>
  <tr><td>Camera angle</td><td><code>a low camera angle looking up</code></td><td>The image is captured with a low camera angle looking up.</td></tr>
</table>
<p class="note">An entry that starts with "Adult woman ..." becomes a "She is ..." sentence (for example "Adult woman lounging on a
chaise" becomes "She is lounging on a chaise"). An entry that already starts with "She" is used as written, and so are
whole-scene entries.</p>
"""),
        ("Reset library", STYLE + """
<h2>Reset library</h2>
<p>If something has gone wrong, <b>Reset library...</b> (top right of the Library tab) puts everything back exactly as it was
when the app was first installed.</p>
<p>It removes the lists and entries you added, your on/off changes and your saved options (the Builder goes back to its
defaults too). It does <i>not</i> remove your saved prompts.</p>
<p>Your safety net:</p>
<ul>
  <li>The built-in presets are rebuilt from the original data, which the app never changes.</li>
  <li>Before anything is deleted, a backup copy of your current library is saved (the newest 10 are kept).</li>
  <li>If the original data cannot be found or read, nothing is changed. If anything fails half-way, everything is put back.</li>
  <li>The confirmation window has <b>Cancel</b> as its default button.</li>
</ul>
"""),
        ("Where your data is", STYLE + """
<h2>Where your data is</h2>
<table>
  <tr><td>Your library, your own presets, saved prompts and settings</td><td><code>@DB@</code></td></tr>
  <tr><td>Automatic backups (made before every reset)</td><td><code>@BACKUPS@</code></td></tr>
  <tr><td>The original preset data (never changed by the app)</td><td><code>@STAGING@</code></td></tr>
</table>
<p>Back up <code>library.db</code> if your own presets or saved prompts matter to you. To go back to an earlier copy, close the
app and replace <code>library.db</code> with a file from the backups folder, keeping the name <code>library.db</code>.</p>
""".replace("@DB@", db_path).replace("@BACKUPS@", backup_folder).replace("@STAGING@", staging_folder)),
        ("Troubleshooting", STYLE + """
<h2>Troubleshooting</h2>
<h3>A paragraph is missing from the prompt</h3>
<p>You cleared that row, or <b>Whole-scene presets</b> is ticked (a scene can cover other parts), or the pose was an adult
scene (which covers the rest). Untick those and press <b>Wildcard</b>.</p>
<h3>There is no eye colour</h3>
<p>The Eye colour row is set to <i>None</i>. Choose a real colour, or press <b>Clear</b> on that row.</p>
<h3>There is no Clothing paragraph</h3>
<p>The row is empty, or an adult scene was picked (adult scenes describe the clothing themselves).</p>
<h3>I cannot find a prompt I saved</h3>
<p>If it contains an adult scene it is hidden until <b>Adult content</b> is ticked in the Builder. The Saved tab says how
many are hidden.</p>
<h3>The app says the preset library is missing</h3>
<p>The original preset data folder is not where the app expects it (see <i>Where your data is</i>). Copy the whole app folder
again rather than moving single files.</p>
<h3>The app will not start</h3>
<p>Start it with <code>run_promptbuilder.bat</code>. The first run creates its own environment and downloads PySide6, so it
needs an internet connection once. Python 3.10 to 3.14 must be installed.</p>
"""),
        ("About", STYLE + f"""
<h2>ComfyUI Prompt Builder V2</h2>
<p>Version {__version__}</p>
<p>A preset and wildcard prompt builder for Krea 2 style prompts. Everything runs on your computer: there is no AI model, no
internet connection needed after installing, and nothing is sent anywhere.</p>
<p>Press F1 at any time to come back to this page.</p>
<h3>Licence</h3>
<p>Copyright &copy; 2026 Ezdub69. This program is free software: you can redistribute it and modify it under the terms of the
GNU General Public License, version 3 or (at your option) any later version. It comes with no warranty. The full text is in
the file <code>LICENSE</code> in the app folder.</p>
<p>The app is built with PySide6 (Qt for Python).</p>
"""),
    ]
