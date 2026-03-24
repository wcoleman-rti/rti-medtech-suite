# resources/fonts/ — Download Google Fonts at configure time.
#
# Variable-weight TTF files are fetched from a pinned commit of the
# google/fonts GitHub repository and verified with SHA-256 hashes.
# No font binaries are stored in the source tree.

set(_GFONTS_COMMIT "3d6da8b416357e1f6a32fbff76b22d52ad1e9bc5")
set(_GFONTS_BASE
    "https://github.com/google/fonts/raw/${_GFONTS_COMMIT}")
set(_FONTS_OUT "${CMAKE_CURRENT_BINARY_DIR}/downloaded")

# Each entry: filename, url-path (percent-encoded brackets), sha256
set(_FONT_SPECS
    "RobotoCondensed.ttf"
    "ofl/robotocondensed/RobotoCondensed%5Bwght%5D.ttf"
    "dace262afcee68a5276f200d8026c57221735c0118ab5fda8c2c0d3dc409a8d0"

    "RobotoCondensed-Italic.ttf"
    "ofl/robotocondensed/RobotoCondensed-Italic%5Bwght%5D.ttf"
    "78f643b1923008b00dfc9b371a2ecd4d80a017722925f1a3fac9940be56d1b7d"

    "Montserrat.ttf"
    "ofl/montserrat/Montserrat%5Bwght%5D.ttf"
    "0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7"

    "Montserrat-Italic.ttf"
    "ofl/montserrat/Montserrat-Italic%5Bwght%5D.ttf"
    "51607f316bc020e59f03cbf51543eecffbea501c0b31d73e5b82927c5cca442c"

    "RobotoMono.ttf"
    "ofl/robotomono/RobotoMono%5Bwght%5D.ttf"
    "66a80e79d17e4c7cabd162e2916578a4cc08fd19eef6e2a643305eae9c567b2b"

    "RobotoMono-Italic.ttf"
    "ofl/robotomono/RobotoMono-Italic%5Bwght%5D.ttf"
    "49ac343bb7b070071e53f0a8a501d68d140ed98ebd0a43b6b8fb96cf22f09ff7"
)

list(LENGTH _FONT_SPECS _n)
math(EXPR _last "${_n} - 1")
foreach(_i RANGE 0 ${_last} 3)
    math(EXPR _j "${_i} + 1")
    math(EXPR _k "${_i} + 2")
    list(GET _FONT_SPECS ${_i} _filename)
    list(GET _FONT_SPECS ${_j} _urlpath)
    list(GET _FONT_SPECS ${_k} _sha256)

    set(_dest "${_FONTS_OUT}/${_filename}")
    if(NOT EXISTS "${_dest}")
        message(STATUS "Downloading font: ${_filename}")
        file(DOWNLOAD
            "${_GFONTS_BASE}/${_urlpath}"
            "${_dest}"
            EXPECTED_HASH SHA256=${_sha256}
            TLS_VERIFY ON
        )
    endif()
endforeach()

install(DIRECTORY "${_FONTS_OUT}/"
    DESTINATION share/resources/fonts
    FILES_MATCHING PATTERN "*.ttf")
