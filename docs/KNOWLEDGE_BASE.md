# 📝 How to Write Knowledge Base Files

Knowledge base files are plain text files that LibBee uses to answer
questions about your library. The better your files, the better LibBee answers.

---

## File Format

Each file must start with these three header lines:

```
SOURCE: https://library.youruniversity.edu/hours
TITLE: Library Hours and Locations
LAST_UPDATED: 2026-01-15
```

Then write the content in plain English below.

---

## Example Files

### library_hours.txt
```
SOURCE: https://library.youruniversity.edu/hours
TITLE: Library Hours and Locations
LAST_UPDATED: 2026-01-15

Main Library (Building A):
Monday – Thursday: 8:00 AM – 11:00 PM
Friday: 8:00 AM – 6:00 PM
Saturday: 10:00 AM – 8:00 PM
Sunday: 12:00 PM – 8:00 PM

Branch Library (Science Building):
Monday – Friday: 9:00 AM – 6:00 PM
Saturday – Sunday: Closed

Holiday hours may vary. Check our website for updates:
https://library.youruniversity.edu/hours
```

### borrowing_policy.txt
```
SOURCE: https://library.youruniversity.edu/borrowing
TITLE: Borrowing Policies and Loan Periods
LAST_UPDATED: 2026-01-15

Loan Periods:
- Books: 4 weeks, renewable up to 3 times
- DVDs: 1 week, not renewable
- Laptops: 4 hours, in-library use only
- Journals: In-library use only

Renewals:
Renew online at: https://library.youruniversity.edu/account
Or call: +1-555-123-4567

Fines:
- Books: $0.25 per day overdue
- DVDs: $1.00 per day overdue

Interlibrary Loan (ILL):
Request items not in our collection:
https://library.youruniversity.edu/ill
Processing time: 3-7 business days
```

### databases.txt
```
SOURCE: https://library.youruniversity.edu/databases
TITLE: Electronic Databases and Resources
LAST_UPDATED: 2026-01-15

Engineering and Technology:
- IEEE Xplore: https://ieeexplore.ieee.org
- ScienceDirect: https://sciencedirect.com
- Scopus: https://scopus.com
- Knovel: https://knovel.com

Medicine and Health Sciences:
- PubMed: https://pubmed.ncbi.nlm.nih.gov (free)
- ClinicalKey: https://clinicalkey.com
- Cochrane Library: https://cochranelibrary.com
- UpToDate: https://uptodate.com

Business:
- Business Source Complete (EBSCO): access via library website
- Emerald Insight: https://emerald.com
- ProQuest: https://proquest.com

All databases accessible remotely with university credentials.
For help: https://library.youruniversity.edu/askus
```

### faq.txt
```
SOURCE: https://library.youruniversity.edu/faq
TITLE: Frequently Asked Questions
LAST_UPDATED: 2026-01-15

Q: How do I access library resources from home?
A: All electronic resources are available remotely. Visit our website,
click on the database, and log in with your university username and password.
VPN is not required. URL: https://library.youruniversity.edu/eresources

Q: How do I reserve a study room?
A: Book study rooms online at: https://library.youruniversity.edu/rooms
Rooms can be reserved up to 7 days in advance.
Maximum booking: 2 hours per day per student.

Q: Can I suggest a book purchase?
A: Yes! Submit purchase suggestions at:
https://library.youruniversity.edu/suggest
We review all requests and aim to acquire within 4 weeks.

Q: How do I get my ORCID ID?
A: ORCID is a free persistent identifier for researchers.
Register at: https://orcid.org
The library can help connect your ORCID to your publications.
Guide: https://library.youruniversity.edu/orcid

Q: What citation management tools does the library support?
A: We support RefWorks, Zotero, and Mendeley.
RefWorks guide: https://library.youruniversity.edu/refworks

Q: How do I contact a librarian?
A: Ask a Librarian service: https://library.youruniversity.edu/askus
Phone: +1-555-123-4567
Email: library@youruniversity.edu
In-person: Main Library Information Desk (Level 1)
```

### staff_contacts.txt
```
SOURCE: https://library.youruniversity.edu/staff
TITLE: Library Staff Directory
LAST_UPDATED: 2026-01-15

Library Director:
Name: [Director Name]
Email: director@library.youruniversity.edu

Research and Reference Services:
Name: [Librarian Name]
Role: Research & Access Services Librarian
Email: research@library.youruniversity.edu
Specialties: Research support, database training, literature reviews

Medical Library:
Name: [Medical Librarian Name]
Role: Medical Librarian
Location: Health Sciences Building, Room 101
Email: medlib@library.youruniversity.edu

Technical Services:
Name: [Technical Librarian Name]
Role: Systems and Digital Services Librarian
Email: systems@library.youruniversity.edu

For general inquiries: library@youruniversity.edu
Ask a Librarian: https://library.youruniversity.edu/askus
```

---

## Tips for Good Knowledge Files

### ✅ DO:
- Write in plain English — no HTML, no markdown
- Include full URLs for every service mentioned
- Include contact information (email, phone, location)
- Use Q&A format for FAQs
- One topic per file (hours, borrowing, databases, staff...)
- Update the `LAST_UPDATED` date when content changes
- Be specific — include room numbers, floor numbers, exact hours
- Include alternative phrasings of common questions

### ❌ DON'T:
- Use HTML tags or markdown formatting
- Include confidential information
- Copy large blocks of legalese
- Make files larger than 50KB each — split into multiple files

---

## Recommended Files to Create

| File | Priority | Content |
|------|----------|---------|
| `library_hours.txt` | 🔴 Essential | Opening hours all locations |
| `borrowing_policy.txt` | 🔴 Essential | Loan periods, fines, renewals |
| `faq.txt` | 🔴 Essential | 20–50 common questions |
| `databases.txt` | 🔴 Essential | All electronic resources with URLs |
| `staff_contacts.txt` | 🟡 Important | Staff names, roles, emails |
| `services.txt` | 🟡 Important | ILL, printing, scanning, rooms |
| `research_guides.txt` | 🟡 Important | LibGuides, subject guides |
| `open_access.txt` | 🟢 Optional | OA publishing, APC, policies |
| `orcid_refworks.txt` | 🟢 Optional | Research tools guides |
| `medical_library.txt` | 🟢 Optional | Medical library specific info |

---

## After Uploading Files

1. Upload your `.txt` files to the `knowledge/` folder in your HF Space
2. Go to Admin Panel → System tab
3. Click **🔄 Rebuild RAG**
4. Verify: `✅ Rebuilt: X chunks from Y files`
5. Test by asking LibBee about your library hours

> **Tip:** Rebuild RAG after every content update. Changes don't take effect until you rebuild.
