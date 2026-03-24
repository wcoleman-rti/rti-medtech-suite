# resources/ — shared GUI assets (fonts, images, stylesheets)

add_subdirectory(fonts)

install(DIRECTORY images/ DESTINATION share/resources/images
    FILES_MATCHING PATTERN "*.png" PATTERN "*.svg")
install(FILES styles/medtech.qss DESTINATION share/resources/styles)
