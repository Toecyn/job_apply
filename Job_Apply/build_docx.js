const { Document, Packer, Paragraph, TextRun, AlignmentType, BorderStyle, LevelFormat, PageBreak } = require('docx');
const fs = require('fs');

const args = process.argv.slice(2);
const tempPath = args[0];
const outputPath = args[1];
const data = JSON.parse(fs.readFileSync(tempPath));

const BLUE = "1F4E79";
const LIGHT_BLUE = "2E75B6";
const DARK = "1A1A1A";
const MID = "444444";
const LIGHT = "555555";
const MARGIN = { top: 580, right: 780, bottom: 580, left: 780 };

const NAME_SIZE = 52;
const SUBTITLE_SIZE = 21;
const CONTACT_SIZE = 18;
const SECTION_SIZE = 24;
const ROLE_CO_SIZE = 21;
const ROLE_TI_SIZE = 20;
const BODY_SIZE = 21;
const COMP_SIZE = 20;

function sh(text) {
  return new Paragraph({
    children: [new TextRun({ text: text.toUpperCase(), bold: true, size: SECTION_SIZE, color: BLUE, font: "Arial" })],
    spacing: { before: 120, after: 40 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LIGHT_BLUE, space: 2 } }
  });
}

function rt(co, ti, dates, loc) {
  return [
    new Paragraph({
      spacing: { before: 36, after: 0 },
      children: [
        new TextRun({ text: co, bold: true, size: ROLE_CO_SIZE, color: DARK, font: "Arial" }),
        new TextRun({ text: "   |   " + dates + "   |   " + loc, size: ROLE_TI_SIZE, color: LIGHT, font: "Arial" })
      ]
    }),
    new Paragraph({
      spacing: { before: 0, after: 20 },
      children: [new TextRun({ text: ti, italics: true, bold: true, size: ROLE_TI_SIZE, color: LIGHT_BLUE, font: "Arial" })]
    })
  ];
}

function bl(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, size: BODY_SIZE, color: DARK, font: "Arial" })],
    spacing: { before: 18, after: 18 }
  });
}

function sp(s) {
  return new Paragraph({ children: [new TextRun("")], spacing: { before: 0, after: s || 24 } });
}

const children = [];

children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 24 },
  children: [new TextRun({ text: (data.name || "RUFUS SOBAYO").toUpperCase(), bold: true, size: NAME_SIZE, color: BLUE, font: "Arial" })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 20 },
  children: [new TextRun({ text: data.title || "Senior Analytics Professional", size: SUBTITLE_SIZE, color: MID, font: "Arial" })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 60 },
  children: [new TextRun({ text: (data.contact.location || "Remote") + "  |  " + data.contact.phone + "  |  " + data.contact.email, size: CONTACT_SIZE, color: LIGHT, font: "Arial" })]
}));

children.push(sh("Professional Summary"));
children.push(new Paragraph({
  spacing: { before: 40, after: 40 },
  children: [new TextRun({ text: data.summary, size: BODY_SIZE, color: DARK, font: "Arial" })]
}));

children.push(sh("Core Competencies"));
const comps = data.core_competencies || [];
for (let i = 0; i < comps.length; i += 3) {
  children.push(new Paragraph({
    spacing: { before: i === 0 ? 28 : 0, after: i + 3 >= comps.length ? 36 : 8 },
    children: [new TextRun({ text: comps.slice(i, i + 3).join("   |   "), size: COMP_SIZE, color: DARK, font: "Arial" })]
  }));
}

children.push(sh("Technical Stack"));
children.push(new Paragraph({
  spacing: { before: 28, after: 36 },
  children: [new TextRun({ text: (data.technical_stack || []).join("   |   "), size: COMP_SIZE, color: DARK, font: "Arial" })]
}));

children.push(sh("Professional Experience"));

const experience = data.experience || [];
experience.forEach(function(role, idx) {
  if (idx === 1) {
    children.push(new Paragraph({ children: [new PageBreak()] }));
  } else if (idx > 1) {
    children.push(sp(24));
  }
  rt(role.company, role.title, role.start + " - " + role.end, role.location).forEach(p => children.push(p));
  (role.bullets || []).forEach(b => children.push(bl(typeof b === "string" ? b : b.text)));
});

children.push(sh("Education & Certification"));
(data.education || []).forEach(edu => children.push(new Paragraph({
  spacing: { before: 32, after: 6 },
  children: [
    new TextRun({ text: edu.degree + "  ", bold: true, size: BODY_SIZE, color: DARK, font: "Arial" }),
    new TextRun({ text: edu.institution + ", " + edu.location + "  |  " + edu.year, size: BODY_SIZE, color: LIGHT, font: "Arial" })
  ]
})));
(data.certifications || []).forEach(cert => children.push(new Paragraph({
  spacing: { before: 6, after: 6 },
  children: [
    new TextRun({ text: cert.name + "  ", bold: true, size: BODY_SIZE, color: DARK, font: "Arial" }),
    new TextRun({ text: cert.issuer + "  |  " + cert.year, size: BODY_SIZE, color: LIGHT, font: "Arial" })
  ]
})));

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "\u2022",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 320, hanging: 200 } } }
      }]
    }]
  },
  styles: { default: { document: { run: { font: "Arial", size: BODY_SIZE, color: DARK } } } },
  sections: [{ properties: { page: { size: { width: 12240, height: 15840 }, margin: MARGIN } }, children }]
});

Packer.toBuffer(doc).then(b => {
  fs.writeFileSync(outputPath, b);
  console.log("SUCCESS:" + outputPath);
}).catch(e => console.error("ERROR:" + e.message));
