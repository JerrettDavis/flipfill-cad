Feature: Slicing a generated body into multiple named parts

  Scenario: Slicing a case into front bezel, center support, and rear shell
    Given a new project with a rounded-box envelope sized like a handheld case
    And a screen, a battery, and mounting screws positioned inside it
    When the project is generated
    Then generation succeeds with no errors
    When I add a horizontal slice named "Front Bezel" near the front face
    And I add a horizontal slice named "Center Support" further back
    And the project is generated again with slicing enabled
    Then generation produces exactly 3 bodies
    And every produced body is a valid, positive-volume solid
    And the bodies are named "Front Bezel", "Center Support", and "Remainder"
    And every body's STEP export opens as a valid solid
