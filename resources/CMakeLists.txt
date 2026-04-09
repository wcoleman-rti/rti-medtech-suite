# resources/ — shared GUI assets (fonts, images)

add_subdirectory(fonts)

install(DIRECTORY images/ DESTINATION share/resources/images
    FILES_MATCHING PATTERN "*.png" PATTERN "*.svg")
