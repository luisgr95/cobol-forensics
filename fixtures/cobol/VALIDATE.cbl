      *----------------------------------------------------------------*
      * VALIDATE  CUSTOMER RECORD EDIT CHECKS                          *
      * SYNTHETIC SAMPLE. Not derived from any real system.            *
      *                                                                *
      * Written in the older style on purpose: paragraph-driven flow
      * with GO TO, a dynamic CALL, and a CICS LINK. These are the
      * constructs the inventory report is meant to surface.           *
      *----------------------------------------------------------------*
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALIDATE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-EDIT-PGM                     PIC X(8).
       01  WS-ERROR-CODE                   PIC 9(4) COMP.
       01  WS-TODAY.
           05  WS-TODAY-YYYY               PIC 9(4).
           05  WS-TODAY-MM                 PIC 9(2).
           05  WS-TODAY-DD                 PIC 9(2).
       LINKAGE SECTION.
       01  LK-CUSTOMER-RECORD              PIC X(172).
       01  LK-REJECT-COUNT                 PIC S9(9) COMP-3.
       PROCEDURE DIVISION USING LK-CUSTOMER-RECORD
                                LK-REJECT-COUNT.
       MAIN-EDIT.
           MOVE ZERO TO WS-ERROR-CODE
           ACCEPT WS-TODAY FROM DATE YYYYMMDD
           IF LK-CUSTOMER-RECORD (1:8) = SPACES
               MOVE 1001 TO WS-ERROR-CODE
               GO TO EDIT-FAILED
           END-IF
           IF LK-CUSTOMER-RECORD (9:1) NOT = 'A' AND
              LK-CUSTOMER-RECORD (9:1) NOT = 'C' AND
              LK-CUSTOMER-RECORD (9:1) NOT = 'S'
               MOVE 1002 TO WS-ERROR-CODE
               GO TO EDIT-FAILED
           END-IF
           PERFORM EXTERNAL-EDIT
           GO TO EDIT-DONE.
       EXTERNAL-EDIT.
           MOVE 'EDITADDR' TO WS-EDIT-PGM
           CALL WS-EDIT-PGM USING LK-CUSTOMER-RECORD
                                  WS-ERROR-CODE
           IF WS-ERROR-CODE NOT = ZERO
               EXEC CICS LINK
                   PROGRAM('ERRLOGR')
                   COMMAREA(WS-ERROR-CODE)
                   LENGTH(2)
               END-EXEC
           END-IF.
       EDIT-FAILED.
           ADD 1 TO LK-REJECT-COUNT
           EXEC CICS WRITEQ TD
               QUEUE('CSMT')
               FROM(WS-ERROR-CODE)
               LENGTH(2)
           END-EXEC.
       EDIT-DONE.
           GOBACK.
