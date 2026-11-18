Attribute VB_Name = "Ollama3DProof"
Option Explicit

Private Const ADDIN_VERSION As String = "1.0.0"

Public Function Ollama3D_Ping() As String
    Ollama3D_Ping = "ollama3d-proof|" & ADDIN_VERSION
End Function

Public Function ExportVBOM(ByVal workbookPath As String, ByVal outputDirectory As String, ByVal runId As String) As String
    Dim source As Workbook
    Dim sheet As Worksheet
    Dim openedHere As Boolean
    Dim lastRow As Long
    Dim rowIndex As Long
    Dim itemCount As Long
    Dim vbomPath As String
    Dim proofPath As String
    Dim xmlText As String
    Dim proofText As String

    On Error GoTo Failed
    If Len(Dir$(workbookPath)) = 0 Then Err.Raise vbObjectError + 100, , "Workbook not found: " & workbookPath
    If Len(Dir$(outputDirectory, vbDirectory)) = 0 Then Err.Raise vbObjectError + 101, , "Output directory not found: " & outputDirectory
    If Len(runId) <> 32 Then Err.Raise vbObjectError + 102, , "Invalid run_id"

    Set source = FindOpenWorkbook(workbookPath)
    If source Is Nothing Then
        Set source = Application.Workbooks.Open(workbookPath, UpdateLinks:=False, ReadOnly:=True, AddToMru:=False)
        openedHere = True
    End If
    Set sheet = source.Worksheets("BOM")
    ValidateHeaders sheet

    vbomPath = JoinPath(outputDirectory, "materials.vbom")
    proofPath = JoinPath(outputDirectory, "excel-proof.json")
    xmlText = "<?xml version=""1.0"" encoding=""utf-8""?>" & vbCrLf & _
              "<vbom format=""proof-v1"" source=""" & XmlEscape(source.Name) & """ run_id=""" & XmlEscape(runId) & """>" & vbCrLf

    lastRow = sheet.Cells(sheet.Rows.Count, 1).End(xlUp).Row
    For rowIndex = 2 To lastRow
        If Len(Trim$(CStr(sheet.Cells(rowIndex, 1).Value2))) > 0 And _
           Left$(CStr(sheet.Cells(rowIndex, 1).Value2), 10) <> "Demo data:" Then
            ValidateRow sheet, rowIndex
            xmlText = xmlText & "  <item object=""" & XmlEscape(CStr(sheet.Cells(rowIndex, 1).Value2)) & _
                      """ material=""" & XmlEscape(CStr(sheet.Cells(rowIndex, 2).Value2)) & _
                      """ color=""" & XmlEscape(UCase$(CStr(sheet.Cells(rowIndex, 3).Value2))) & _
                      """ roughness=""" & CStr(CDbl(sheet.Cells(rowIndex, 4).Value2)) & _
                      """ metallic=""" & CStr(CDbl(sheet.Cells(rowIndex, 5).Value2)) & """/>" & vbCrLf
            itemCount = itemCount + 1
        End If
    Next rowIndex
    If itemCount <> 3 Then Err.Raise vbObjectError + 103, , "Expected exactly three BOM rows"
    xmlText = xmlText & "</vbom>" & vbCrLf
    WriteUtf8File vbomPath, xmlText

    proofText = "{" & _
        """producer"":""ollama3d-vba""," & _
        """addin_version"":""" & ADDIN_VERSION & """," & _
        """macro"":""ExportVBOM""," & _
        """run_id"":""" & JsonEscape(runId) & """," & _
        """source_excel"":""" & JsonEscape(workbookPath) & """," & _
        """vbom_path"":""" & JsonEscape(vbomPath) & """," & _
        """items"":" & CStr(itemCount) & "," & _
        """completed_at"":""" & Format$(Now, "yyyy-mm-dd\Thh:nn:ss") & """}"
    WriteUtf8File proofPath, proofText

    ExportVBOM = vbomPath
CleanUp:
    On Error Resume Next
    If openedHere And Not source Is Nothing Then source.Close SaveChanges:=False
    Exit Function
Failed:
    Dim message As String
    message = Err.Description
    On Error Resume Next
    If openedHere And Not source Is Nothing Then source.Close SaveChanges:=False
    On Error GoTo 0
    Err.Raise vbObjectError + 110, "Ollama3DProof.ExportVBOM", message
End Function

Private Function FindOpenWorkbook(ByVal workbookPath As String) As Workbook
    Dim candidate As Workbook
    For Each candidate In Application.Workbooks
        If StrComp(candidate.FullName, workbookPath, vbTextCompare) = 0 Then
            Set FindOpenWorkbook = candidate
            Exit Function
        End If
    Next candidate
End Function

Private Sub ValidateHeaders(ByVal sheet As Worksheet)
    Dim expected As Variant
    Dim index As Long
    expected = Array("Object", "Material", "ColorHex", "Roughness", "Metallic")
    For index = 0 To UBound(expected)
        If CStr(sheet.Cells(1, index + 1).Value2) <> CStr(expected(index)) Then
            Err.Raise vbObjectError + 120, , "Unexpected BOM header at column " & CStr(index + 1)
        End If
    Next index
End Sub

Private Sub ValidateRow(ByVal sheet As Worksheet, ByVal rowIndex As Long)
    Dim objectName As String
    Dim colorHex As String
    Dim roughness As Double
    Dim metallic As Double
    objectName = CStr(sheet.Cells(rowIndex, 1).Value2)
    If objectName <> "Upper" And objectName <> "Sole" And objectName <> "Laces" Then Err.Raise vbObjectError + 121, , "Unknown object: " & objectName
    If Len(Trim$(CStr(sheet.Cells(rowIndex, 2).Value2))) = 0 Then Err.Raise vbObjectError + 122, , "Missing material"
    colorHex = UCase$(CStr(sheet.Cells(rowIndex, 3).Value2))
    If Len(colorHex) <> 7 Or Left$(colorHex, 1) <> "#" Or Not IsHexColor(Mid$(colorHex, 2)) Then Err.Raise vbObjectError + 123, , "Invalid ColorHex"
    If Not IsNumeric(sheet.Cells(rowIndex, 4).Value2) Or Not IsNumeric(sheet.Cells(rowIndex, 5).Value2) Then Err.Raise vbObjectError + 124, , "Invalid material values"
    roughness = CDbl(sheet.Cells(rowIndex, 4).Value2)
    metallic = CDbl(sheet.Cells(rowIndex, 5).Value2)
    If roughness < 0 Or roughness > 1 Or metallic < 0 Or metallic > 1 Then Err.Raise vbObjectError + 125, , "Material values must be between zero and one"
End Sub

Private Function IsHexColor(ByVal value As String) As Boolean
    Dim parsed As Long
    On Error GoTo InvalidValue
    If Len(value) <> 6 Then Exit Function
    parsed = CLng("&H" & value)
    IsHexColor = True
    Exit Function
InvalidValue:
    IsHexColor = False
End Function

Private Sub WriteUtf8File(ByVal path As String, ByVal content As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.WriteText content
    stream.SaveToFile path, 2
    stream.Close
End Sub

Private Function JoinPath(ByVal folder As String, ByVal filename As String) As String
    If Right$(folder, 1) = "\" Then JoinPath = folder & filename Else JoinPath = folder & "\" & filename
End Function

Private Function XmlEscape(ByVal value As String) As String
    value = Replace(value, "&", "&amp;")
    value = Replace(value, """", "&quot;")
    value = Replace(value, "<", "&lt;")
    value = Replace(value, ">", "&gt;")
    XmlEscape = value
End Function

Private Function JsonEscape(ByVal value As String) As String
    value = Replace(value, "\", "\\")
    value = Replace(value, """", "\""")
    JsonEscape = value
End Function
