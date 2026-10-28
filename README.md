# АРМ Специалиста по выпускникам
Веб-приложение на Flask и MS SQL Server для автоматизации учета выпускников, расчета GPA, формирования PDF-справок и сбора статистики.

erDiagram
    Roles ||--o{ Users : "имеет"
    Users ||--o{ Audit_Logs : "совершает"
    Academic_Groups ||--o{ Students : "включает"
    Students ||--o| Diplomas : "получает"
    Students ||--o| Employment : "имеет"

    Roles {
        int RoleID PK
        string RoleName
    }
    
    Users {
        int UserID PK
        string Username
        string PasswordHash
        string FullName
        int RoleID FK
    }
    
    Academic_Groups {
        int GroupID PK
        string GroupName
        int AdmissionYear
        int GraduationYear
    }
    
    Programs {
        int ProgramID PK
        string ProgramCode
        string ProgramName
        string Qualification
    }
    
    Students {
        int StudentID PK
        string LastName
        string FirstName
        string MiddleName
        string IIN
        string StudyForm
        int GroupID FK
    }
    
    Diplomas {
        int DiplomaID PK
        int StudentID FK
        string DiplomaNumber
        string RegistrationNumber
        date IssueDate
        float GPA
        bit IsHonors
    }
    
    Employment {
        int EmploymentID PK
        int StudentID FK
        string Companyname
        string Position
    }
    
    Audit_Logs {
        int LogID PK
        int UserID FK
        string Action
        datetime ActionDate
    }