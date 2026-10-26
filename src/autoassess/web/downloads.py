"""Owned assignment downloads and a printable class report."""

from fastapi import HTTPException, Request
from fastapi.responses import Response
from markupsafe import Markup

from autoassess.web.exports import csv_bytes, grade_rows, pdf_zip, report_content, xlsx_bytes


def mount_download_routes(app, store, templates):
    def assignment(request, assignment_id):
        row = store.assignment(assignment_id, request.state.teacher['id'])
        if row is None:
            raise HTTPException(404, 'Assignment not found')
        return row

    @app.get('/assignments/{assignment_id}/export/{format}')
    def export(request: Request, assignment_id: int, format: str):
        row = assignment(request, assignment_id)
        if format not in ('csv', 'xlsx', 'zip'):
            raise HTTPException(404, 'Download format not found')
        if format == 'zip':
            if not store.assignment_summary(assignment_id)['graded']:
                raise HTTPException(400, 'Grade at least one sheet before downloading marked PDFs.')
            content = pdf_zip(store, row)
            media_type = 'application/zip'
            suffix = 'marked-sheets.zip'
        else:
            header, rows = grade_rows(store, row)
            content = csv_bytes(header, rows) if format == 'csv' else xlsx_bytes(header, rows)
            media_type = 'text/csv; charset=utf-8' if format == 'csv' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            suffix = f'grades.{format}'
        return Response(content, media_type=media_type, headers={'Content-Disposition': f'attachment; filename="assignment-{assignment_id}-{suffix}"',
                                                               'Cache-Control': 'no-store'})

    @app.get('/assignments/{assignment_id}/report')
    def report(request: Request, assignment_id: int):
        row = assignment(request, assignment_id)
        body, pairs = report_content(store, row)
        return templates.TemplateResponse(request=request, name='class_report.html', context={
            'teacher': request.state.teacher, 'assignment': row, 'classroom': store.classroom(row['class_id'], request.state.teacher['id']),
            # The reused core renderer escapes every user-derived value.
            'report_body': Markup(body), 'pairs': pairs})
