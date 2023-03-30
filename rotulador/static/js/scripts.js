$(document).ready(function () {
    M.AutoInit();
    update_hidden_counts();
});

//// Visualization control
// Toggle between short and full visualization for a text
function toggle_pannel(id) {
    $("#short_" + id).toggle();
    $("#full_" + id).toggle();
}

// Toggle visibility for a day
function toggle_day(id) {
    $(".toggle_inline_" + id).each(toggle_inline);
    $(".toggle_" + id).toggle();
}

// Auxiliary function to toggle visibility of round buttons
function toggle_inline() {
    if ($(this).is(':visible'))
        $(this).css('display', 'none');
    else
        $(this).css('display', 'inline-block');
}

// Toggle the visibility of hidden items
function toggle_hidden(show) {
    $(".hidden-entry").toggle()
    if (show) {
        $('#show-hidden').val("True")
    } else {
        $('#show-hidden').val("False")
    }
}

// Expands all visible entries
function expand_all() {
    $('.btn-expand').each(function () {
        if ($(this).is(':visible'))
            $(this).click();
    })
}

// Retract all visible entries
function retract_all() {
    $('.btn-retract').each(function () {
        if ($(this).is(':visible'))
            $(this).click();
    })
}

//// Visualization update functions
// Updates the hidden counts for each date
function update_hidden_counts() {
    $('.day').each(function () {
        var n = $(this).find('.hidden-entry').length
        if (n == 1)
            $(this).find('.hidden-count').text("(1 oculto)");
        else if (n > 1)
            $(this).find('.hidden-count').text("(" + n + " ocultos)");
        else
            $(this).find('.hidden-count').text("");
    })
}

//// Search form functions
// Clear a date field
function clear_date(id) {
    $("#" + id).val([]);
    M.Datepicker.getInstance($("#" + id)).setDate();
}

// Creates a Date object from "DD/MM/YYYY" string
function datestr(datestr) {
    var splitDate = datestr.split("/");
    return new Date(splitDate[2], splitDate[1] - 1, splitDate[0]);
}

//// Backend communication functions
// Sends a command to the backend
function run_command(cmd, args) {
    var URL = "commands?cmd=" + cmd;

    for (i in args) {
        URL = URL + "&" + args[i];
    }

    fetch(URL)
        .then(response => response.json())
        .then((data) => {
            console.log(data);
            if (data.type == 'OK') {
                M.toast({ html: data.text, displayLength: 4000, classes: 'teal darken-3' });
                if (data.request.callback) {
                    eval(data.callback);
                }
            }
            else {
                M.toast({ html: "ERROR: " + data.text, displayLength: 20000, classes: 'red darken-4' });
                if (data.request.fail_callback) {
                    eval(data.fail_callback);
                }
            }
        })
}

// Calls then backend to hide an entry
function hide_one(text_id) {
    run_command('hide-one', ['txt_id=' + text_id, 'callback=hide_text("' + text_id + '");'])
}

// Calls then backend to hide all equal an entry
function hide_all(text_id) {
    run_command('hide-all', ['txt_id=' + text_id, 'callback=hide_text("' + text_id + '");']);
}

// Calls then backend to unhide an entry
function unhide(text_id) {
    run_command('show', ['txt_id=' + text_id, 'callback=unhide_text("' + text_id + '");']);
}

function add_label_yes(patient_id, label_id, label) {
    run_command('add-label', ['patient_id=' + patient_id, 'label=' + label, 'value=True', 'callback=mark_yes("' + label_id + '");']);
}

function add_label_no(patient_id, label_id, label) {
    run_command('add-label', ['patient_id=' + patient_id, 'label=' + label, 'value=False', 'callback=mark_no("' + label_id + '");']);
}

function create_label(label) {
    run_command('new-label', ['label=' + label])
}

//// Callback functions to hide unhide entries
// Change the state of a text to hidden
function hide_text(id) {
    if (!$('.btn-hide').is(':visible'))
        $("#text_" + id).hide();
    $("#text_" + id).addClass("hidden-entry");
    $("#full_" + id).removeClass("grey");
    $("#short_" + id).removeClass("grey");
    $("#full_" + id).removeClass("lighten-4");
    $("#short_" + id).removeClass("lighten-3");
    $("#full_" + id).addClass("red");
    $("#short_" + id).addClass("red");
    $("#full_" + id).addClass("lighten-5");
    $("#short_" + id).addClass("lighten-4");
    $("#full_" + id + " .btn-to-hide").css('display', 'none');
    $("#full_" + id + " .btn-to-show").css('display', 'inline-block');
    update_hidden_counts();
}

// Change the state of a text from hidden
function unhide_text(id) {
    $("#text_" + id).removeClass("hidden-entry");
    $("#full_" + id).removeClass("red");
    $("#short_" + id).removeClass("red");
    $("#full_" + id).removeClass("lighten-5");
    $("#short_" + id).removeClass("lighten-4");
    $("#full_" + id).addClass("grey");
    $("#short_" + id).addClass("grey");
    $("#full_" + id).addClass("lighten-4");
    $("#short_" + id).addClass("lighten-3");
    $("#full_" + id + " .btn-to-hide").css('display', 'inline-block');
    $("#full_" + id + " .btn-to-show").css('display', 'none');
    update_hidden_counts();
}

function mark_yes(label_id) {
    $("#yes_" + label_id).removeClass("grey-text");
    $("#yes_" + label_id).addClass("green-text");
    $("#no_" + label_id).addClass("grey-text");
    $("#no_" + label_id).removeClass("red-text");
}

function mark_no(label_id) {
    $("#no_" + label_id).removeClass("grey-text");
    $("#no_" + label_id).addClass("red-text");
    $("#yes_" + label_id).addClass("grey-text");
    $("#yes_" + label_id).removeClass("green-text");
}