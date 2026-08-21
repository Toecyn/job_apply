const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, LevelFormat, PageBreak
} = require('docx');
const fs = require('fs');
const path = require('path');

const BLUE = "1F4E79";
const LIGHT_BLUE = "2E75B6";
const DARK = "1A1A1A";
const MID = "444444";
const LIGHT = "666666";

const MARGIN = { top: 640, right: 800, bottom: 640, left: 800 };
const CONTENT_WIDTH = 12240 - MARGIN.left - MARGIN.right;

const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function sectionHeader(text) {
  return new Paragraph({
    children: [new TextRun({ text: text.toUpperCase(), bold: true, size: 22, color: BLUE, font: "Arial" })],
    spacing: { before: 160, after: 60 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: LIGHT_BLUE, space: 2 } }
  });
}

function roleHeader(company, title, dates, location) {
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [Math.round(CONTENT_WIDTH * 0.55), Math.round(CONTENT_WIDTH * 0.45)],
    borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideH: noBorder, insideV: noBorder },
    rows: [
      new TableRow({ children: [
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.55), type: WidthType.DXA }, margins: { top: 0, bottom: 0, left: 0, right: 0 }, children: [
          new Paragraph({ children: [new TextRun({ text: company, bold: true, size: 22, color: DARK, font: "Arial" })] })
        ]}),
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.45), type: WidthType.DXA }, margins: { top: 0, bottom: 0, left: 0, right: 0 }, children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: dates, size: 20, color: LIGHT, font: "Arial" })] })
        ]})
      ]}),
      new TableRow({ children: [
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.55), type: WidthType.DXA }, margins: { top: 0, bottom: 0, left: 0, right: 0 }, children: [
          new Paragraph({ children: [new TextRun({ text: title, italics: true, size: 20, color: LIGHT_BLUE, font: "Arial" })] })
        ]}),
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.45), type: WidthType.DXA }, margins: { top: 0, bottom: 0, left: 0, right: 0 }, children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: location, size: 20, color: LIGHT, font: "Arial" })] })
        ]})
      ]})
    ]
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text, size: 20, color: DARK, font: "Arial" })],
    spacing: { before: 40, after: 40 }
  });
}

function spacer(size = 60) {
  return new Paragraph({ children: [new TextRun("")], spacing: { before: 0, after: size } });
}

function buildResume(resumeData, outputPath) {
  const { name, contact, summary, areas_of_expertise, technical_stack, experience, education, certifications } = resumeData;

  const children = [];

  // Name
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 40 },
    children: [new TextRun({ text: name, bold: true, size: 40, color: BLUE, font: "Arial" })]
  }));

  // Subtitle
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 40 },
    children: [new TextRun({ text: "MBA | Senior Data & Analytics Professional", size: 22, color: MID, font: "Arial" })]
  }));

  // Contact
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 100 },
    children: [new TextRun({
      text: `${contact.location}  |  ${contact.phone}  |  ${contact.email}`,
      size: 19, color: LIGHT, font: "Arial"
    })]
  }));

  // Summary
  children.push(sectionHeader("Professional Summary"));
  children.push(new Paragraph({
    spacing: { before: 80, after: 80 },
    children: [new TextRun({ text: summary, size: 20, color: DARK, font: "Arial" })]
  }));

  // Areas of expertise
  children.push(sectionHeader("Areas of Expertise"));
  const half = Math.ceil(areas_of_expertise.length / 2);
  const left = areas_of_expertise.slice(0, half);
  const right = areas_of_expertise.slice(half);

  children.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [Math.round(CONTENT_WIDTH / 2), Math.round(CONTENT_WIDTH / 2)],
    borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideH: noBorder, insideV: noBorder },
    rows: [new TableRow({ children: [
      new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH / 2), type: WidthType.DXA }, margins: { top: 30, bottom: 30, left: 0, right: 40 }, children:
        left.map(item => new Paragraph({ spacing: { before: 20, after: 20 }, children: [new TextRun({ text: `• ${item}`, size: 20, color: DARK, font: "Arial" })] }))
      }),
      new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH / 2), type: WidthType.DXA }, margins: { top: 30, bottom: 30, left: 40, right: 0 }, children:
        right.map(item => new Paragraph({ spacing: { before: 20, after: 20 }, children: [new TextRun({ text: `• ${item}`, size: 20, color: DARK, font: "Arial" })] }))
      })
    ]})]
  }));

  // Tech stack
  children.push(new Paragraph({
    spacing: { before: 80, after: 60 },
    children: [
      new TextRun({ text: "Technical Stack:  ", bold: true, size: 20, color: DARK, font: "Arial" }),
      new TextRun({ text: technical_stack.join(" · "), size: 20, color: DARK, font: "Arial" })
    ]
  }));

  // Experience
  children.push(sectionHeader("Professional Experience"));

  experience.forEach((role, index) => {
    if (index === 1) {
      children.push(new Paragraph({ children: [new PageBreak()] }));
    } else {
      children.push(spacer(60));
    }

    children.push(roleHeader(role.company, role.title, `${role.start} - ${role.end}`, role.location));
    children.push(spacer(40));

    role.bullets.forEach(b => {
      const text = typeof b === 'string' ? b : b.text;
      children.push(bullet(text));
    });
  });

  // Education
  children.push(sectionHeader("Education & Certifications"));
  children.push(spacer(60));

  const eduRows = [];

  education.forEach(edu => {
    eduRows.push(new TableRow({ children: [
      new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.65), type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 0, right: 0 }, children: [
        new Paragraph({ children: [new TextRun({ text: edu.degree, bold: true, size: 20, color: DARK, font: "Arial" })] }),
        new Paragraph({ children: [new TextRun({ text: `${edu.institution}, ${edu.location}`, size: 20, color: LIGHT, font: "Arial" })] })
      ]}),
      new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.35), type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 0, right: 0 }, children: [
        new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: edu.year, size: 20, color: LIGHT, font: "Arial" })] })
      ]})
    ]}));
  });

  if (certifications) {
    certifications.forEach(cert => {
      eduRows.push(new TableRow({ children: [
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.65), type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 0, right: 0 }, children: [
          new Paragraph({ children: [new TextRun({ text: cert.name, bold: true, size: 20, color: DARK, font: "Arial" })] }),
          new Paragraph({ children: [new TextRun({ text: cert.issuer, size: 20, color: LIGHT, font: "Arial" })] })
        ]}),
        new TableCell({ borders: noBorders, width: { size: Math.round(CONTENT_WIDTH * 0.35), type: WidthType.DXA }, margins: { top: 40, bottom: 40, left: 0, right: 0 }, children: [
          new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: cert.year, size: 20, color: LIGHT, font: "Arial" })] })
        ]})
      ]}));
    });
  }

  children.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [Math.round(CONTENT_WIDTH * 0.65), Math.round(CONTENT_WIDTH * 0.35)],
    borders: { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder, insideH: noBorder, insideV: noBorder },
    rows: eduRows
  }));

  const doc = new Document({
    numbering: {
      config: [{
        reference: "bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 360, hanging: 240 } } }
        }]
      }]
    },
    styles: {
      default: { document: { run: { font: "Arial", size: 20, color: DARK } } }
    },
    sections: [{
      properties: {
        page: { size: { width: 12240, height: 15840 }, margin: MARGIN }
      },
      children
    }]
  });

  return Packer.toBuffer(doc).then(buffer => {
    fs.writeFileSync(outputPath, buffer);
    console.log(`Resume saved to: ${outputPath}`);
    return outputPath;
  });
}

// Run directly to generate master resume
if (require.main === module) {
  const resumeData = JSON.parse(fs.readFileSync('master_resume.json', 'utf8'));
  const outputDir = 'output';
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir);
  const outputPath = path.join(outputDir, 'Olu_Sobayo_Resume.docx');
  buildResume(resumeData, outputPath)
    .then(() => console.log('Done.'))
    .catch(err => console.error('Error:', err));
}

module.exports = { buildResume };
